"""The CI workflow is a file this repository controls, so it is checked like one.

A malformed workflow does not fail loudly. GitHub creates a run, fails it at zero seconds
with "this run likely failed because of a workflow file issue", and runs no job — which
reads like infrastructure trouble rather than a syntax error in a tracked file. That state
lasted a day and eleven runs here, because nothing on this side ever parsed the thing.

The specific mistake is worth naming, because it is invisible on a screen. In YAML a value
beginning with a quote ENDS at its closing quote, so

    run: "$RUNNER_TEMP/venv/bin/python" -m pip install ...

is not a long command. It is a quoted scalar followed by text the parser cannot place. It
looks exactly like a shell line that would work.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _workflow_files():
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))


def test_there_is_at_least_one_workflow_to_check():
    assert _workflow_files(), "no workflow files found, so this test proves nothing"


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_every_workflow_parses(path):
    yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_every_step_command_survives_parsing_whole(path):
    """A truncated `run:` is the failure this file exists for.

    Parsing alone would accept a command silently cut at a quote boundary in some shapes,
    so each recorded command is checked for the balance a shell would need.
    """
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    for job in document["jobs"].values():
        for step in job["steps"]:
            command = step.get("run")
            if command is None:
                continue
            assert command.count('"') % 2 == 0, command
            assert command.strip(), "an empty run step does nothing but pass"


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_the_branch_this_work_happens_on_is_covered(path):
    """CI watching only `main` had nothing to say about any commit since Stage 4.

    The package job exists to catch a defect that has shipped three times; a trigger that
    never fires on the branch carrying the work is the same as not having it.
    """
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    # YAML 1.1 reads a bare `on` key as the boolean True.
    triggers = document.get("on", document.get(True))
    branches = triggers["push"]["branches"]
    assert "main" in branches
    assert any(pattern.startswith("docs/") for pattern in branches), branches
