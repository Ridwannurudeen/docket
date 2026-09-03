"""What a built distribution carries, checked against what the source tree holds.

Source-tree tests import through the checkout, so they pass whether or not a package is
declared for the build. An installed Docket carries only what `pyproject.toml` names, and
twice now a new subpackage has landed without being added to that list — `docket.advantage.v2`
during Stage 4, then `docket.agents.venus` and `docket.agents.yield_router`, which between them
are two of the four scored marketplace categories. Both times every test passed.
"""

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RELEASE_BUNDLE = ROOT / "deploy" / "release_bundle.py"
BUILD_REQUIREMENTS = ROOT / "deploy" / "build-requirements.txt"


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


def _source_manifest() -> str:
    return (ROOT / "docs/source-deploy-manifest.md").read_text(encoding="utf-8")


def _manifest_packages() -> set[str]:
    import re

    match = re.search(
        r"`pyproject\.toml` declares:\s*```text\s*(.*?)\s*```",
        _source_manifest(),
        re.S,
    )
    assert match is not None, "the source manifest has no explicit package inventory"
    return {line.strip() for line in match.group(1).splitlines() if line.strip()}


def _manifest_artifact_rows() -> list[tuple[str, str]]:
    import re

    return re.findall(
        r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", _source_manifest(), re.M
    )


def _manifest_artifact_hashes() -> dict[str, str]:
    rows = _manifest_artifact_rows()
    hashes = dict(rows)
    assert len(hashes) == len(rows), "the evidence manifest repeats an artifact path"
    return hashes


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


def test_build_backend_is_exactly_pinned():
    with (ROOT / "pyproject.toml").open("rb") as fh:
        build_system = tomllib.load(fh)["build-system"]

    assert build_system["requires"] == ["setuptools==83.0.0"]


def test_builder_dependencies_and_transitives_are_fully_hash_locked():
    import re

    assert BUILD_REQUIREMENTS.is_file()
    contents = BUILD_REQUIREMENTS.read_text(encoding="utf-8")
    assert "--only-binary=:all:" in contents
    logical_lines = [
        line.strip()
        for line in contents.replace("\\\n", " ").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "--"))
    ]
    expected = {
        "build": "1.5.0",
        "colorama": "0.4.6",
        "packaging": "26.3",
        "pyproject-hooks": "1.2.0",
        "setuptools": "83.0.0",
        "uv": "0.11.16",
    }
    locked = {line.split("==", 1)[0]: line for line in logical_lines}

    assert set(locked) == set(expected)
    for name, version in expected.items():
        line = locked[name]
        assert line.startswith(f"{name}=={version}")
        hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})(?:\s|$)", line)
        assert hashes, f"{name} has no reviewed SHA-256"
        assert len(hashes) == len(set(hashes)), f"{name} repeats a SHA-256"
    assert "; os_name == 'nt'" in locked["colorama"]


def test_release_bundle_creates_and_populates_a_locked_temporary_builder():
    script = RELEASE_BUNDLE.read_text(encoding="utf-8")

    assert 'BUILD_LOCK_PATH = "deploy/build-requirements.txt"' in script
    builder_venv = script.index('builder_venv = temporary_root / "builder-venv"')
    create_venv = script.index('"venv",', builder_venv)
    hash_install = script.index('"--require-hashes",', create_venv)
    build = script.index('"--no-isolation",', hash_install)
    assert "str(build_lock)" in script[hash_install:build]
    assert "str(builder_python)" in script[hash_install:]
    assert builder_venv < create_venv < hash_install < build
    assert "isolated wheel build failed" not in script


def test_release_bundle_builder_refuses_a_dirty_worktree(tmp_path):
    assert RELEASE_BUNDLE.is_file()
    repo = tmp_path / "repo"
    deploy = repo / "deploy"
    deploy.mkdir(parents=True)
    shutil.copy2(RELEASE_BUNDLE, deploy / RELEASE_BUNDLE.name)
    (repo / "tracked.txt").write_text("committed\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Docket Tests",
            "-c",
            "user.email=docket-tests@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    (repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(deploy / RELEASE_BUNDLE.name),
            "build",
            str(tmp_path / "bundle"),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "working tree is not clean" in result.stderr
    assert not (tmp_path / "bundle").exists()


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX ownership is required")
@pytest.mark.parametrize("writable_target", ["bundle", "asset"])
def test_secure_bundle_verification_refuses_untrusted_write_permissions(
    tmp_path, writable_target
):
    from tests.test_release_scripts import _write_release_manifest, _write_wheel

    bundle = tmp_path / "release-bundle"
    copied_deploy = bundle / "deploy"
    shutil.copytree(ROOT / "deploy", copied_deploy)
    wheel = bundle / "docket-0.1.0-py3-none-any.whl"
    digest = _write_wheel(wheel)
    manifest = _write_release_manifest(wheel, digest, deploy=copied_deploy)
    if writable_target == "bundle":
        bundle.chmod(0o777)
    else:
        (copied_deploy / "journald-docket.conf").chmod(0o666)

    result = subprocess.run(
        [
            sys.executable,
            str(copied_deploy / "release_bundle.py"),
            "verify",
            str(manifest),
            str(copied_deploy),
            "--secure-owner",
            str(os.getuid()),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "group/world writable" in result.stderr


def test_ci_builds_and_smokes_the_real_provenance_bundle():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    # Three jobs bootstrap pip from the hash-pinned build requirements: `test`,
    # `package`, and the browser `e2e` job, which needs the same locked environment
    # because its fixture starts the real uvicorn out of it. The count is here so a
    # bootstrap that stops being hash-pinned cannot be added quietly; raise it
    # deliberately when a job is added, never delete it.
    assert (
        workflow.count(
            "python -m pip install --require-hashes --only-binary=:all: "
            "-r deploy/build-requirements.txt"
        )
        == 3
    )
    assert "python -m pip install uv==" not in workflow
    assert "python -m pip install build==" not in workflow
    assert "--output-file deploy/runtime-requirements.txt" in workflow
    assert "git diff --exit-code -- deploy/runtime-requirements.txt" in workflow
    assert "python deploy/release_bundle.py build" in workflow
    assert "release-bundle/deploy/runtime-requirements.txt" in workflow
    assert "pip install --require-hashes" in workflow
    assert workflow.count("--only-binary=:all:") == 4
    assert "pip install --no-deps" in workflow
    assert 'docket-venv/bin/python" -m pip check' in workflow
    assert 'python-version: ["3.11", "3.12"]' in workflow


def test_runbook_uses_the_integrity_bound_release_commands():
    runbook = (ROOT / "docs/deployment-runbook.md").read_text(encoding="utf-8")
    normalized = " ".join(runbook.split())

    for required in (
        "setuptools==83.0.0",
        "python -m pip install --require-hashes --only-binary=:all: -r "
        "deploy/build-requirements.txt",
        "python deploy/release_bundle.py build",
        "without build isolation",
        "pip install --require-hashes",
        "--only-binary=:all:",
        "pip install --no-deps",
        "tar --no-same-owner -xf -",
        "release-manifest.json",
        "root-owned",
        "reverified immediately before",
        "integrity binding, not artifact authenticity",
        "temporary builder virtual environment",
        "whole-process lock",
        "/run/docket/release.lock",
        "all six timers",
        "directory fsync",
        "two-directory rename",
        "power loss",
    ):
        assert required in normalized
    assert "setuptools>=77" not in runbook
    assert "python -m pip install build==" not in runbook
    assert "<40-hex-source-commit>" not in runbook
    assert "'$source_commit' '$wheel_sha'" not in runbook


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


def test_source_manifest_names_the_exact_declared_package_inventory():
    assert _manifest_packages() == _packages_declared()


def test_source_manifest_names_every_v3_spec_and_source_exactly_once():
    expected = {
        path.relative_to(ROOT).as_posix()
        for directory in (
            ROOT / "docket/advantage/v3/specs",
            ROOT / "docket/advantage/v3/sources",
        )
        for path in directory.iterdir()
        if path.is_file()
    }
    published = {
        path
        for path in _manifest_artifact_hashes()
        if path.startswith(
            ("docket/advantage/v3/specs/", "docket/advantage/v3/sources/")
        )
    }

    assert published == expected


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


def test_v3_operator_runbooks_keep_experiment_ledgers_in_the_repository():
    for relative in (
        "docs/runbooks/yield-v3-02-run.md",
        "docs/runbooks/yield-v3-06-assisted-run.md",
        "docs/runbooks/range-v3-05-run.md",
        "docs/deployment-runbook.md",
    ):
        runbook = (ROOT / relative).read_text(encoding="utf-8")
        normalized = " ".join(runbook.split())
        assert (
            "Experiment arms run on the workstation against the repository tree."
            in normalized
        )
        assert "The installed package is read-only" in normalized
        assert (
            "only after it is committed to the repository and that commit is redeployed"
            in normalized
        )


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

    rows = _manifest_artifact_hashes().items()
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
        "-P",
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
        'test "$(</opt/docket/RELEASE-commit.txt)" = "$expected_commit"',
        'cmp -s "$service" /opt/docket/deploy/systemd/docket-v3-range-capture.service',
        'cmp -s "$timer" /opt/docket/deploy/systemd/docket-v3-range-capture.timer',
        '(timer, "OnCalendar", "2026-08-26 12:03:00 UTC")',
        '(timer, "Unit", "docket-v3-range-capture.service")',
        "/opt/docket/.venv/bin/python -P -m docket.advantage.v3.capture "
        "v3-05-range-doctor /var/lib/docket/v3-capture/range",
        "systemctl is-active docket-v3-range-capture.service && test -f",
        "Range arm check failed; only if the timer missed 12:03Z",
    ):
        assert required in runbook
    assert "systemctl is-active docket-v3-range-capture.service; test -f" not in runbook
