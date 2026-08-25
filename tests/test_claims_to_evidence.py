import hashlib
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "claims-to-evidence.md"
FILE_SHA256 = re.compile(
    r"\bfile\b[^|\n]{0,200}?\bSHA-256 `([0-9a-f]{64})`", re.IGNORECASE
)


def _tracked_sha256() -> set[str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    paths = [Path(raw.decode("utf-8")) for raw in listed.split(b"\0") if raw]
    return {hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}


def _missing_file_citations(ledger: str, tracked: set[str]) -> list[str]:
    return sorted(set(FILE_SHA256.findall(ledger)) - tracked)


def test_every_claimed_file_sha256_resolves_to_a_tracked_file():
    ledger = LEDGER.read_text(encoding="utf-8")
    citations = FILE_SHA256.findall(ledger)

    assert citations, "the claims ledger contains no file SHA-256 citations"
    missing = _missing_file_citations(ledger, _tracked_sha256())
    assert missing == [], (
        "claims-to-evidence.md cites file SHA-256 digests that match no tracked file: "
        + ", ".join(missing)
    )
