import hashlib
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "claims-to-evidence.md"
EVIDENCE_REPRODUCTION = ROOT / "docs" / "evidence-reproduction.md"
FILE_CITATION = re.compile(
    r"\bfile `([^`\n]+)` SHA-256 `([0-9a-f]{64})`", re.IGNORECASE
)
V3_04_SPEC_ID = "v3-04-warden-security"
FALSE_ADVANTAGE = re.compile(
    r"\b(?:advantages?|outperform(?:s|ed|ing)?|beat(?:s|en|ing)?)\b"
    r"|\b(?:faster|better)(?:\W+\w+){0,3}\W+than\b",
    re.IGNORECASE,
)
JUDGE_FACING_DOCUMENTS = (
    ROOT / "README.md",
    *(sorted((ROOT / "docs/submission").glob("*.md"))),
    ROOT / "docs/claims-to-evidence.md",
    ROOT / "docs/operational-evidence.md",
    ROOT / "docket/api/static/llms.txt",
    ROOT / "docket/api/static/SKILL.md",
    ROOT / "docket/api/web/advantage-v3.html",
)
CURRENT_SETTLEMENT_DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "docs/api-and-payment-semantics.md",
    ROOT / "docs/claims-to-evidence.md",
    ROOT / "docs/deployment-runbook.md",
    ROOT / "docs/evidence-reproduction.md",
    ROOT / "docs/source-deploy-manifest.md",
    *(sorted((ROOT / "docs/submission").glob("*.md"))),
)


def _tracked_sha256() -> dict[str, str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    paths = [raw.decode("utf-8") for raw in listed.split(b"\0") if raw]
    return {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths
    }


def _missing_file_citations(ledger: str, tracked: dict[str, str]) -> list[str]:
    return sorted(
        path
        for path, digest in FILE_CITATION.findall(ledger)
        if tracked.get(path) != digest
    )


def _publication_blocks(document: str) -> list[str]:
    document = re.sub(r"(?ms)^```.*?^```\s*$", "", document)
    without_links = re.sub(r"\]\([^)]+\)", "]", document)
    without_links = re.sub(r"https?://\S+", "", without_links)
    blocks = []
    for paragraph in re.split(r"\n\s*\n", without_links):
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        if any(line.startswith("|") for line in lines):
            blocks.extend(line for line in lines if line.startswith("|"))
            continue
        for item in re.split(r"(?m)^(?=(?:[-*+] |\d+\. ))", paragraph):
            normalized = " ".join(item.split())
            if normalized:
                blocks.append(normalized)
    return blocks


def test_file_citation_is_bound_to_its_path():
    digest = "a" * 64
    ledger = f"artifact file `expected.json` SHA-256 `{digest}`"

    assert _missing_file_citations(ledger, {"other.json": digest}) == ["expected.json"]


def test_publication_blocks_ignore_fenced_reproduction_commands():
    document = (
        """Prose naming v3-04-warden-security.\n\n```text\ndocket.advantage.v3\n```"""
    )

    assert _publication_blocks(document) == ["Prose naming v3-04-warden-security."]


def test_every_claimed_file_sha256_resolves_to_a_tracked_file():
    ledger = LEDGER.read_text(encoding="utf-8")
    citations = FILE_CITATION.findall(ledger)

    assert citations, "the claims ledger contains no file SHA-256 citations"
    missing = _missing_file_citations(ledger, _tracked_sha256())
    assert missing == [], (
        "claims-to-evidence.md cites tracked files whose SHA-256 does not match: "
        + ", ".join(missing)
    )


def test_evidence_reproduction_lists_all_current_v3_families():
    document = EVIDENCE_REPRODUCTION.read_text(encoding="utf-8")

    assert "V3 has exactly seven stage-one specifications:" in document
    for spec_path in sorted((ROOT / "docket/advantage/v3/specs").glob("*.json")):
        assert spec_path.stem in document
    assert "V3-02 and v3-05 have no claimed primaries" not in document


def test_current_claims_do_not_erase_the_approved_settlement_canary():
    stale_claims = (
        "No settlement has occurred",
        "No settlement has run",
        "never been exercised live",
        "settlement legs remain `not_yet_exercised`",
    )

    violations = []
    for path in CURRENT_SETTLEMENT_DOCUMENTS:
        document = path.read_text(encoding="utf-8")
        for claim in stale_claims:
            if claim.lower() in document.lower():
                violations.append(f"{path.relative_to(ROOT)}: {claim}")

    assert violations == [], "\n".join(violations)


def test_v3_04_never_cooccurs_with_a_false_agent_advantage_claim():
    violations = []
    for path in JUDGE_FACING_DOCUMENTS:
        for block in _publication_blocks(path.read_text(encoding="utf-8")):
            match = FALSE_ADVANTAGE.search(block) if V3_04_SPEC_ID in block else None
            if match:
                violations.append(
                    f"{path.relative_to(ROOT)}: {match.group(0)!r} in {block!r}"
                )

    assert violations == [], "\n".join(violations)
