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
        "v3/provenance/*.json",
    } <= declared
    assert "v3/runs/*.json" not in declared


def test_the_live_audit_claim_evidence_is_resolved_as_package_data():
    package_root = ROOT / "docket/advantage"
    carried = {
        path.relative_to(package_root).as_posix()
        for pattern in _advantage_package_data()
        for path in package_root.glob(pattern)
        if path.is_file()
    }

    assert "experiments/01-liquidity/live-audit.json" in carried


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
    assert not stale, (
        "the manifest names digests these files do not have:\n  " + "\n  ".join(stale)
    )


def _unit_directives(name: str) -> dict[str, str]:
    """Directives only. Comments mention the settings they explain, so a substring search
    over the raw text would find `RandomizedDelaySec` in the note saying it is absent."""
    text = (Path(__file__).resolve().parents[1] / "deploy/systemd" / name).read_text(
        encoding="utf-8"
    )
    # systemd continues a directive onto the next line after a trailing backslash.
    text = text.replace("\\\n", " ")
    directives = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "[")):
            continue
        key, _, value = line.partition("=")
        directives[key.strip()] = value.strip()
    return directives


def test_the_capture_timer_names_a_family_the_installed_package_can_resolve():
    """A unit file is not covered by any other test, and this one fires once, on a date.

    An absolute path would have been worse than wrong: /opt/docket/docket is the previous
    release's source tree, so a path there resolves, parses, and captures against a
    registration that is not the deployed one. Naming the family means the running Docket
    supplies the spec — and this test fails now if that name ever stops resolving.
    """
    from docket.advantage.v3.capture import _resolve_spec

    exec_start = _unit_directives("docket-v3-capture.service")["ExecStart"].split()
    assert "docket.advantage.v3.capture" in exec_start
    family = exec_start[exec_start.index("docket.advantage.v3.capture") + 1]
    assert _resolve_spec(family).is_file()


def test_the_capture_timer_prearms_without_jitter_and_persists():
    """A catch-up activation is safe because the capture refuses late before any HTTP."""
    timer = _unit_directives("docket-v3-capture.timer")
    assert "RandomizedDelaySec" not in timer
    assert timer["Persistent"] == "true"
    assert timer["AccuracySec"] == "1s"


def test_the_range_capture_timer_names_its_registered_family_and_output():
    from docket.advantage.v3.capture import _resolve_spec

    exec_start = _unit_directives("docket-v3-range-capture.service")[
        "ExecStart"
    ].split()
    assert exec_start == [
        "/opt/docket/.venv/bin/python",
        "-m",
        "docket.advantage.v3.capture",
        "v3-05-range-doctor",
        "/var/lib/docket/v3-capture/range",
    ]
    module = exec_start.index("docket.advantage.v3.capture")
    assert exec_start[module + 1 :] == [
        "v3-05-range-doctor",
        "/var/lib/docket/v3-capture/range",
    ]
    assert _resolve_spec(exec_start[module + 1]).is_file()


def test_the_range_capture_timer_prearms_after_yield_without_jitter_and_persists():
    timer = _unit_directives("docket-v3-range-capture.timer")
    assert timer["OnCalendar"] == "2026-08-26 12:03:00 UTC"
    assert timer["Unit"] == "docket-v3-range-capture.service"
    assert "RandomizedDelaySec" not in timer
    assert timer["Persistent"] == "true"
    assert timer["AccuracySec"] == "1s"


def test_the_range_runbook_verifies_the_released_units_and_armed_state():
    runbook = (ROOT / "docs/runbooks/range-v3-05-run.md").read_text(encoding="utf-8")

    for required in (
        "test \"$(</opt/docket/RELEASE-commit.txt)\" = \"$expected_commit\"",
        'cmp -s "$service" /opt/docket/deploy/systemd/docket-v3-range-capture.service',
        'cmp -s "$timer" /opt/docket/deploy/systemd/docket-v3-range-capture.timer',
        '(timer, "OnCalendar", "2026-08-26 12:03:00 UTC")',
        '(timer, "Unit", "docket-v3-range-capture.service")',
        "docket.advantage.v3.capture v3-05-range-doctor /var/lib/docket/v3-capture/range",
        "systemctl is-active docket-v3-range-capture.service && test -f",
        "Range arm check failed; only if the timer missed 12:03Z",
    ):
        assert required in runbook
    assert (
        "systemctl is-active docket-v3-range-capture.service; test -f" not in runbook
    )
