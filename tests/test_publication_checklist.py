import re
from pathlib import Path


CHECKLIST = Path(__file__).resolve().parents[1] / "docs" / "publication-checklist.md"
ROOT = Path(__file__).resolve().parents[1]
NAMED_WINDOWS_USER_ROOT = re.compile(
    r"(?:[A-Za-z]:\\{1,2}|/[A-Za-z]:/)Users(?:\\{1,2}|/)[^\\/\s`<|]+"
)


def test_publication_checklist_covers_every_public_flip_boundary():
    text = " ".join(CHECKLIST.read_text(encoding="utf-8").split())
    remote_heads = text.index("git ls-remote --heads origin")
    visibility = text.index("**Change repository visibility**")
    rulesets = text.index("disables all push rulesets")
    secret_scanning = text.index("**Secret scanning**")
    sha_equality = text.index("$publicSha -ne (git rev-parse main)")

    assert "docs/deliberation-round2" in text
    assert "feat/phase0" in text
    assert remote_heads < visibility < rulesets < secret_scanning < sha_equality


def test_public_docs_do_not_publish_named_windows_user_roots():
    public_docs = [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in public_docs
        if NAMED_WINDOWS_USER_ROOT.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
