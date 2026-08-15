"""The frozen vendor vocabulary a Warden input lock validates its labels against.

The snapshot is the answer to "which attack classes exist", and the input lock will accept
any label that appears in it. That makes the contents of `classes` a security-relevant list
rather than documentation: a mechanism code admitted here would be scorable as though an
attacker had written it.
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "docket/advantage/v3/sources/warden-vendor-snapshot.json"
BODY = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

# The two codes that describe how the scanner reached a detection rather than anything an
# attacker writes. v2 excluded them for the same reason on 2026-08-10.
MECHANISM_CODES = {"CORPUS_MATCH", "STATISTICAL_ANOMALY"}


def test_the_vocabulary_excludes_the_mechanism_codes():
    """No hand-authored payload can carry these as ground truth, so a payload labelled with
    one could never be right or wrong — it would be unfalsifiable evidence."""
    assert MECHANISM_CODES.isdisjoint(BODY["classes"])
    assert MECHANISM_CODES <= set(BODY["published_codes"])
    assert set(BODY["excluded_codes"]) == MECHANISM_CODES


def test_the_vocabulary_is_exactly_the_published_codes_minus_the_exclusions():
    """The snapshot may not quietly add a class the vendor does not publish, or drop one it
    does. Either would make our answer key disagree with the vendor's own terms, and a miss
    has to be a miss against those terms."""
    assert sorted(BODY["classes"]) == sorted(
        set(BODY["published_codes"]) - MECHANISM_CODES
    )
    assert len(BODY["published_codes"]) == 11
    assert len(BODY["classes"]) == 9


def test_the_snapshot_carries_the_page_it_was_read_from():
    """A derived list with no evidence of its source is a claim, not a snapshot."""
    page = ROOT / BODY["source_page_ref"]
    assert page.is_file()
    assert hashlib.sha256(page.read_bytes()).hexdigest() == BODY["source_page_sha256"]
    assert BODY["source_url"].startswith("https://")


def test_every_published_code_actually_appears_in_the_captured_page():
    """The extraction is re-runnable from the bytes beside it, so a reader does not have to
    take the list on trust."""
    text = (ROOT / BODY["source_page_ref"]).read_text(encoding="utf-8", errors="replace")
    for code in BODY["published_codes"]:
        assert code in text, f"{code} is not in the captured page"


def test_the_hashed_evidence_is_protected_from_line_ending_rewriting():
    """A captured HTTP response is bytes, and git rewrites line endings by default.

    This is not hypothetical here: the page was committed once without protection and the
    object store held 22,336 bytes against 22,560 on disk — 224 stripped carriage returns.
    Every clone would have produced a file failing the digest recorded beside it, and the
    failure would have looked like tampering rather than like a checkout setting.
    """
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    rules = [
        line.strip()
        for line in attributes.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    for path in ("docket/advantage/v3/sources/*", "docket/advantage/v3/specs/*.json"):
        assert f"{path} -text" in rules, f"{path} is not protected from eol rewriting"
