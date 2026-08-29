import re
from collections import defaultdict
from pathlib import Path

from docket.advantage.v3 import report as v3_report

ROOT = Path(__file__).resolve().parents[1]
V3_STATE_DOCS = (
    ROOT / "AI_USAGE.md",
    ROOT / "README.md",
    ROOT / "docs/architecture.md",
    ROOT / "docs/submission/judge-start-here.md",
    ROOT / "docket/api/static/SKILL.md",
    ROOT / "docket/api/static/llms.txt",
)
JUDGE_FACING_DOCS = V3_STATE_DOCS + (
    ROOT / "docs/api-and-payment-semantics.md",
    ROOT / "docs/claims-to-evidence.md",
    ROOT / "docs/evidence-reproduction.md",
    ROOT / "docs/operational-evidence.md",
    ROOT / "docs/source-deploy-manifest.md",
) + tuple(sorted((ROOT / "docs/submission").glob("*.md")))
FAMILY_ID = re.compile(r"`(v3-\d{2}-[a-z0-9-]+)`")
STATE_TOKEN = re.compile(
    r"`(" + "|".join(map(re.escape, v3_report.STATES)) + r")`"
)
VISIBILITY_ROW = re.compile(
    r"^\| Repository visibility \| (?P<visibility>Public|Private) "
    r"\(verified (?P<date>\d{4}-\d{2}-\d{2})\) \|$",
    re.MULTILINE,
)
CURRENT_VISIBILITY = re.compile(
    r"\brepository (?:is|remains)\s+(?:\*\*)?(public|private)(?:\*\*)?"
    r"|\bon a\s+(public|private)\s+repository\b",
    re.IGNORECASE,
)


def _snapshot(payload):
    grouped = defaultdict(list)
    for family in payload["families"]:
        grouped[family["state"]].append(family["spec_id"])
    clauses = []
    for state in sorted(grouped):
        spec_ids = sorted(grouped[state])
        names = " and ".join(f"`{spec_id}`" for spec_id in spec_ids)
        verb = "is" if len(spec_ids) == 1 else "are"
        clauses.append(f"{names} {verb} `{state}`")
    return (
        "At the committed-artifact observation on 2026-08-29, the committed v3 artifacts "
        f"contain {payload['summary']['n_families']} families: {'; '.join(clauses)}."
    )


def test_judge_facing_v3_state_follows_committed_artifacts():
    payload = v3_report.report()
    actual = {family["spec_id"]: family["state"] for family in payload["families"]}
    expected = _snapshot(payload)
    missing = []
    contradictions = []
    for path in JUDGE_FACING_DOCS:
        document = " ".join(path.read_text(encoding="utf-8").split())
        if path in V3_STATE_DOCS and expected not in document:
            missing.append(path.relative_to(ROOT).as_posix())
        for clause in re.split(r";|\.(?:\s|$)", document):
            spec_ids = FAMILY_ID.findall(clause)
            states = set(STATE_TOKEN.findall(clause))
            if not spec_ids or not states:
                continue
            if len(states) != 1:
                contradictions.append(f"{path.name}: ambiguous {clause!r}")
                continue
            state = states.pop()
            contradictions.extend(
                f"{path.name}: {spec_id} says {state}, artifacts say {actual.get(spec_id)}"
                for spec_id in spec_ids
                if actual.get(spec_id) != state
            )
    assert not missing, f"missing exact artifact-derived v3 snapshot {expected!r}: {missing}"
    assert not contradictions, "\n".join(contradictions)


def test_present_repository_visibility_claims_agree_with_manifest_observation():
    manifest = (ROOT / "docs/source-deploy-manifest.md").read_text(encoding="utf-8")
    row = VISIBILITY_ROW.search(manifest)
    assert row is not None, "source manifest has no dated repository visibility row"
    expected = row["visibility"].lower()
    disagreements = []
    for path in JUDGE_FACING_DOCS:
        document = path.read_text(encoding="utf-8")
        claims = [
            next(value for value in match.groups() if value).lower()
            for match in CURRENT_VISIBILITY.finditer(document)
        ]
        disagreements.extend(
            f"{path.relative_to(ROOT)} says {claim}; manifest says {expected}"
            for claim in claims
            if claim != expected
        )
    assert not disagreements, "\n".join(disagreements)
