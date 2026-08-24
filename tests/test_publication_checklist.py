from pathlib import Path


CHECKLIST = (
    Path(__file__).resolve().parents[1] / "docs" / "publication-checklist.md"
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
