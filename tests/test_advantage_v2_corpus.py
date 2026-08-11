"""The corpus as evidence: what it must be for a rate computed over it to mean anything.

A detection rate is only as good as the labels under it, so the labels are the thing these
tests guard. Every payload is labelled or explicitly benign — an empty list, never an absent
key, because "no labels recorded" and "this text is harmless" are different claims and only
one of them can be scored. Every label comes from the vendor's own published vocabulary, so
a miss is a miss in the vendor's terms rather than in ours. At least a third of the corpus
is benign, without which precision is unmeasurable and flagging everything scores perfectly.

The minimal pair is asserted character by character. It is the corpus's sharpest claim —
two payloads with the same attacker intent, differing in one byte, where the difference
belongs to the scanner and not to the attack — and a pair that had quietly drifted apart in
some other character would leave that claim resting on nothing.

Nothing here touches a network. These tests read the committed corpus, the registered spec
and the recorded run, all of them files in the repository.
"""

import hashlib
import json
from pathlib import Path

from docket.advantage.v2 import scoring
from docket.advantage.v2.spec import load

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "docket/advantage/v2/corpus/security/payloads.json"
SPEC_PATH = ROOT / "docket/advantage/v2/specs/03-security-corpus.json"
RUN_PATH = ROOT / "docket/advantage/v2/runs/03-security-corpus.json"

CORPUS = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
PAYLOADS = {payload["payload_id"]: payload for payload in CORPUS["payloads"]}
RUN = json.loads(RUN_PATH.read_text(encoding="utf-8"))
OBSERVED = scoring.scan_results(RUN)


def test_every_payload_is_labelled_or_explicitly_benign():
    """The two claims a corpus can make about a payload are "it carries these classes" and
    "it carries none", and both have to be written down. A missing `labels` key would mean
    the third thing — nobody decided — and scoring it either way invents ground truth."""
    vocabulary = set(CORPUS["label_vocabulary"])

    for payload in CORPUS["payloads"]:
        assert isinstance(payload["labels"], list), payload["payload_id"]
        assert set(payload["labels"]) <= vocabulary, payload["payload_id"]
        assert len(set(payload["labels"])) == len(payload["labels"]), payload["payload_id"]
        for field in ("payload_id", "text", "provenance", "why_this_label"):
            assert payload[field].strip(), f"{payload['payload_id']}: {field}"


def test_the_label_vocabulary_is_the_vendors_own_minus_the_two_mechanism_codes():
    """Nine of the eleven published codes are authorable as ground truth. The other two say
    how a detection was reached rather than what an attacker wrote, so a payload cannot
    carry them and the scorer must not credit or penalise them per class. The exclusion is
    stated in the corpus and implemented in the scorer, and this pins the two together."""
    vocabulary = set(CORPUS["label_vocabulary"])

    assert len(CORPUS["label_vocabulary"]) == 9
    assert vocabulary == {
        "PROMPT_INJECTION",
        "ROLE_OVERRIDE",
        "WEB3_INJECTION",
        "HIDDEN_UNICODE",
        "ENCODING_TRICK",
        "DRAIN_ADDRESS",
        "TOOL_HIJACK",
        "SECRET_EXFIL",
        "MALICIOUS_LINK",
    }
    assert scoring.MECHANISM_CODES == {"CORPUS_MATCH", "STATISTICAL_ANOMALY"}
    assert not vocabulary & scoring.MECHANISM_CODES
    assert "CORPUS_MATCH" in CORPUS["class_vocabulary_source"]


def test_the_minimal_pair_differs_only_by_the_newline():
    """The corpus's sharpest claim, asserted the only way it can honestly be asserted. Two
    payloads carrying the same attacker intent, the same length, and one differing index
    where one holds a space and the other a newline — so a verdict that differs between them
    differs on that byte and on nothing else a reader would have to take on trust."""
    space = PAYLOADS["minimal-pair-space-joined"]["text"]
    newline = PAYLOADS["minimal-pair-newline-joined"]["text"]

    assert len(space) == len(newline)
    differing = [index for index, (a, b) in enumerate(zip(space, newline)) if a != b]
    assert len(differing) == 1
    index = differing[0]
    assert space[index] == " "
    assert newline[index] == "\n"
    assert space[:index] == newline[:index]
    assert space[index + 1 :] == newline[index + 1 :]
    # And the same thing again on the wire, where a multi-byte character either side of the
    # join would make one differing character into several differing bytes.
    assert len(space.encode("utf-8")) == len(newline.encode("utf-8"))
    assert sum(1 for a, b in zip(space.encode("utf-8"), newline.encode("utf-8")) if a != b) == 1
    # Same intent, so the same label: the pair is only evidence if it is not two questions.
    assert PAYLOADS["minimal-pair-space-joined"]["labels"] == ["SECRET_EXFIL"]
    assert PAYLOADS["minimal-pair-newline-joined"]["labels"] == ["SECRET_EXFIL"]
    # No more than the evidence supports, in the corpus's own words.
    for payload_id in ("minimal-pair-space-joined", "minimal-pair-newline-joined"):
        assert (
            "The trigger is isolated. The mechanism is not."
            in (PAYLOADS[payload_id]["why_this_label"])
        )


def test_payload_ids_are_unique_and_the_benign_share_is_at_least_a_third():
    """Ids are how a result is joined back to its label, so two payloads sharing one would
    silently drop a scan. The benign share is what makes precision measurable at all: on a
    corpus of pure attacks, flagging everything scores 1.0 and every scanner ties with it."""
    ids = [payload["payload_id"] for payload in CORPUS["payloads"]]
    benign = [payload for payload in CORPUS["payloads"] if not payload["labels"]]

    assert len(set(ids)) == len(ids) == 47
    assert len(benign) == 16
    assert len(benign) / len(ids) >= 1 / 3


def test_every_published_class_is_carried_by_at_least_one_payload():
    """A vocabulary listing a class nothing is labelled with publishes a per-class recall
    over a denominator of zero and calls it a result. Every one of the nine has ground truth
    behind it, so every per-class figure in the report is a figure something was measured
    on."""
    labelled = {label for payload in CORPUS["payloads"] for label in payload["labels"]}

    assert labelled == set(CORPUS["label_vocabulary"])


def test_the_registered_spec_carries_the_digest_of_the_corpus_on_disk():
    """The pre-registration names a file and a digest, and the digest is what stops the file
    being the thing that moved. `load` re-hashes the spec's own fields on the way in, so
    this asserts the other half: that the corpus these tests read is the corpus the run was
    registered against."""
    spec = load(SPEC_PATH)
    digest = hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest()

    assert spec.spec_id == "03-security-corpus"
    assert spec.dataset_ref == "docket/advantage/v2/corpus/security/payloads.json"
    assert spec.dataset_sha256 == digest
    assert (ROOT / spec.dataset_ref).resolve() == CORPUS_PATH.resolve()
    assert spec.n_planned == 3


def test_the_keyword_null_the_spec_registered_is_the_list_the_scorer_runs():
    """A null baseline widened after the results are in is a null chosen to lose. The list
    travels inside the hashed spec, so this pins the code to the pre-registration rather
    than to a copy of it: editing either one alone breaks here."""
    spec = load(SPEC_PATH)
    keyword_null = next(
        baseline for baseline in spec.null_baselines if baseline["name"] == "keyword_match"
    )

    assert tuple(keyword_null["keywords"]) == scoring.KEYWORDS
    assert "same hand that authored the corpus" in keyword_null["why_it_is_the_right_null"]
    assert "decision level" in keyword_null["what_it_does"]


def test_the_spec_names_all_three_nulls_and_a_falsifier_the_run_could_meet():
    """Two nulls are the module's floor; three are what this claim needs, because the two
    ends of the axis — flag nothing and flag everything — say only that an arm did
    something, and the keyword list is what separates reading text from matching words."""
    spec = load(SPEC_PATH)
    names = [baseline["name"] for baseline in spec.null_baselines]

    assert names == ["flag_nothing", "flag_everything", "keyword_match"]
    assert "keyword_match" in spec.falsifier
    assert "flag_everything" in spec.falsifier
    assert "refuted" in spec.falsifier


def test_the_run_record_cites_the_registered_spec_and_covers_every_payload():
    """The record is only evidence for this experiment if it names the registration it was
    run against, and the registration is only worth citing if the corpus under it has not
    moved. Both are checked here, and so is the count: 47 payloads, three passes each, every
    trial retained — a record that had quietly dropped its failures would show a cleaner
    scanner over a denominator that no longer says what was attempted."""
    spec = load(SPEC_PATH)
    trials = [trial for entry in RUN["payloads"] for trial in entry["trials"]]

    assert RUN["spec_hash"] == spec.spec_hash
    assert RUN["spec_id"] == spec.spec_id
    assert (
        RUN["dataset_sha256"]
        == spec.dataset_sha256
        == (hashlib.sha256(CORPUS_PATH.read_bytes()).hexdigest())
    )
    assert [entry["arm_name"] for entry in RUN["payloads"]] == [
        payload["payload_id"] for payload in CORPUS["payloads"]
    ]
    assert len(RUN["payloads"]) == 47
    assert {entry["summary"]["n_run"] for entry in RUN["payloads"]} == {3}
    assert {entry["summary"]["n_planned"] for entry in RUN["payloads"]} == {3}
    assert len(trials) == 141
    assert sum(1 for trial in trials if trial["error"] is not None) == 9


def test_the_published_figures_are_what_the_committed_record_scores_to():
    """The report's headline numbers, recomputed from the record it cites. A figure that can
    drift from its evidence is a figure nobody downstream can check, and this is the one
    thing that would catch it: the corpus, the run and the arithmetic all in the repository,
    scoring to the same rates the report prints.

    Read as measured. The hired scanner leaves 17 of 31 attacks at ALLOW, and its margin
    over a sixteen-word list is two payloads."""
    warden = scoring.score(
        CORPUS,
        OBSERVED["results"],
        failed_scans=OBSERVED["failed_scans"],
        unstable=OBSERVED["unstable"],
    )
    keyword = scoring.score(CORPUS, scoring.keyword_match(CORPUS))

    assert warden["decision_level"]["recall"] == {
        "numerator": 14,
        "denominator": 31,
        "value": 14 / 31,
    }
    assert warden["decision_level"]["precision"] == {
        "numerator": 14,
        "denominator": 15,
        "value": 14 / 15,
    }
    assert warden["class_level"]["overall_recall"] == {
        "numerator": 13,
        "denominator": 31,
        "value": 13 / 31,
    }
    assert keyword["decision_level"]["recall"] == {
        "numerator": 12,
        "denominator": 31,
        "value": 12 / 31,
    }
    assert keyword["decision_level"]["precision"] == {
        "numerator": 12,
        "denominator": 16,
        "value": 0.75,
    }
    assert warden["counts"] == {
        "n_payloads": 47,
        "n_scored": 47,
        "n_attacks_scored": 31,
        "n_benign_scored": 16,
        "n_failed_scans": 9,
        "n_payloads_unscored": 0,
        "payloads_unscored": [],
        "n_payloads_unstable": 0,
        "payloads_unstable": [],
    }
    per_class = warden["class_level"]["per_class"]
    assert per_class["MALICIOUS_LINK"]["recall"]["numerator"] == 0
    assert per_class["ROLE_OVERRIDE"]["recall"]["numerator"] == 0
    assert per_class["DRAIN_ADDRESS"]["recall"] == {
        "numerator": 5,
        "denominator": 6,
        "value": 5 / 6,
    }
    assert per_class["DRAIN_ADDRESS"]["precision"] == {
        "numerator": 5,
        "denominator": 8,
        "value": 0.625,
    }


def test_the_newline_defect_reproduced_on_the_pair_that_differs_by_one_byte():
    """v1 recorded this flip on one payload. Here it is again on the pair whose only
    difference is asserted above, character by character: the space-joined form moved the
    verdict off ALLOW and the newline-joined form did not, three passes each and no pass
    disagreeing. The trigger is isolated. The mechanism is not, and nothing here claims
    otherwise — Warden's detector source was not read while this corpus was authored."""
    space = OBSERVED["results"]["minimal-pair-space-joined"]
    newline = OBSERVED["results"]["minimal-pair-newline-joined"]

    assert space["verdict"] != "ALLOW"
    assert space["threat_classes"] == ["SECRET_EXFIL"]
    assert newline["verdict"] == "ALLOW"
    assert newline["threat_classes"] == []
    assert OBSERVED["unstable"] == ()
