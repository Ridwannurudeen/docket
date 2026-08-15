"""What a built distribution carries, checked against what the source tree holds.

Source-tree tests import through the checkout, so they pass whether or not a package is
declared for the build. An installed Docket carries only what `pyproject.toml` names, and
twice now a new subpackage has landed without being added to that list — `docket.advantage.v2`
during Stage 4, then `docket.agents.venus` and `docket.agents.yield_router`, which between them
are two of the four scored marketplace categories. Both times every test passed.
"""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _packages_on_disk() -> set[str]:
    """Every importable package in the source tree, as a dotted name."""
    return {
        str(init.parent.relative_to(ROOT)).replace("\\", "/").replace("/", ".")
        for init in ROOT.glob("**/__init__.py")
        if "__pycache__" not in init.parts
        and ".venv" not in init.parts
        and "build" not in init.parts
    }


def _packages_declared() -> set[str]:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return set(tomllib.load(fh)["tool"]["setuptools"]["packages"])


def _advantage_package_data() -> set[str]:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return set(
            tomllib.load(fh)["tool"]["setuptools"]["package-data"]["docket.advantage"]
        )


def test_every_package_in_the_tree_is_declared_for_the_build():
    """An undeclared package is absent from the wheel and present in every test run."""
    missing = _packages_on_disk() - _packages_declared()
    assert not missing, (
        f"these packages exist in the tree but would not ship: {sorted(missing)}. "
        "Add them to [tool.setuptools] packages in pyproject.toml."
    )


def test_no_declared_package_has_gone_missing_from_the_tree():
    """The other direction: a stale name makes the build fail on a fresh checkout."""
    stale = _packages_declared() - _packages_on_disk()
    assert not stale, f"declared but not in the tree: {sorted(stale)}"


def test_each_scored_marketplace_category_has_its_agent_package_declared():
    """The four categories BNB scores are the four Docket must not ship without.

    Named individually rather than derived, so deleting a category's package is a test
    failure rather than a silently smaller set on both sides of the comparison above.
    """
    declared = _packages_declared()
    for package in (
        "docket.agents.pancake",  # rebalancing — Range Doctor
        "docket.agents.grid",  # grid trading — Grid Operator
        "docket.agents.yield_router",  # yield optimisation — Yield Router
        "docket.agents.venus",  # health factor — Health Guard
    ):
        assert package in declared, f"{package} would not ship in a built distribution"


def test_every_v3_state_artifact_has_a_package_data_path():
    """A wheel must not fall back to an earlier state because its evidence stayed in source."""
    declared = _advantage_package_data()

    assert {
        "v3/specs/*.json",
        "v3/inputs/*.json",
        "v3/runs/*.jsonl",
        "v3/sheets/*/*.json",
        "v3/mappings/*.json",
    } <= declared
    assert "v3/runs/*.json" not in declared


def test_the_published_evidence_hashes_match_the_files_they_name():
    """Hand-transcribed digests rot silently, and this table is the one a reader checks.

    Every v3 spec digest in the manifest was stale within a day of being written: the
    protocols were corrected, the files changed, and the document went on naming the old
    bytes. A digest table that disagrees with its own repository is worse than no table,
    because it invites a reader to conclude the evidence was swapped.
    """
    import hashlib
    import re

    manifest = (ROOT / "docs/source-deploy-manifest.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| `([^`]+\.json)` \| `([0-9a-f]{64})` \|$", manifest, re.M)
    assert rows, "the evidence manifest lists no artifact digests"

    stale = []
    for relative, published in rows:
        path = ROOT / relative
        if not path.exists():
            stale.append(f"{relative}: listed but absent")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != published:
            stale.append(f"{relative}: manifest {published[:12]}, file {actual[:12]}")
    assert not stale, "the manifest names digests these files do not have:\n  " + "\n  ".join(stale)
