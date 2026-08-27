import hashlib
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "claims-to-evidence.md"
FILE_CITATION = re.compile(
    r"\bfile `([^`\n]+)` SHA-256 `([0-9a-f]{64})`", re.IGNORECASE
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
        path for path, digest in FILE_CITATION.findall(ledger) if tracked.get(path) != digest
    )


def test_file_citation_is_bound_to_its_path():
    digest = "a" * 64
    ledger = f"artifact file `expected.json` SHA-256 `{digest}`"

    assert _missing_file_citations(ledger, {"other.json": digest}) == ["expected.json"]


def test_every_claimed_file_sha256_resolves_to_a_tracked_file():
    ledger = LEDGER.read_text(encoding="utf-8")
    citations = FILE_CITATION.findall(ledger)

    assert citations, "the claims ledger contains no file SHA-256 citations"
    missing = _missing_file_citations(ledger, _tracked_sha256())
    assert missing == [], (
        "claims-to-evidence.md cites tracked files whose SHA-256 does not match: "
        + ", ".join(missing)
    )
