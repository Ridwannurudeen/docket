"""What the published report must not be able to become.

Two failures are worth a test each. The first is drift: the page is authored HTML, so
nothing but a test stops it from stating one number while `/advantage.json` states
another. Every data-derived block on the page is re-derived here from the experiment
files and asserted present, so editing the evidence without editing the page fails the
build.

The second is quiet sanitisation. Two of the three recorded results are qualified —
one agent arm answered something other than the question it was asked, and one lost
outright — and those are the findings a report like this is most tempted to lose in a
later edit. They are pinned: to the summary, where a reader meets them before any
per-task detail, and to the security task's own section.
"""

import html
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docket.advantage.harness import compare, load
from docket.api import create_app
from docket.store import Store

TASK_IDS = ("01-liquidity", "02-trading", "03-security")
EXPERIMENTS = Path(__file__).resolve().parents[1] / "docket" / "advantage" / "experiments"
STATIC_DIR = Path(__file__).resolve().parents[1] / "docket" / "api" / "static"
# Words that would turn a recorded comparison into a claim about agents in general.
VERDICT_WORDS = ("best", "superior", "proves", "guaranteed")


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "d.sqlite3"
    store = Store(db)
    sid = store.begin_snapshot(chain_id=56, expected=0)
    store.finish_snapshot(sid, sampled=0, expected=0)
    return TestClient(create_app(db, snapshot_id=sid))


@pytest.fixture
def page(client):
    resp = client.get("/advantage", headers={"accept": "text/html"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    return resp.text


def experiments():
    return [load(EXPERIMENTS / f"{task_id}.json") for task_id in TASK_IDS]


def section(page_text, task_id):
    """One task's markup, from its own section to the start of the next one."""
    start = page_text.index(f'id="{task_id}" aria-labelledby=')
    return page_text[start : page_text.index("<section", start + 10)]


def test_the_page_is_served_and_names_all_three_tasks(page):
    assert "<title>" in page
    for task_id in TASK_IDS:
        assert task_id in page, task_id


def test_the_json_carries_all_three_experiments_with_both_arms_populated(client):
    body = client.get("/advantage.json").json()

    assert [exp["task_id"] for exp in body["experiments"]] == list(TASK_IDS)
    assert body["method"] and body["page"] == "/advantage"
    for exp in body["experiments"]:
        assert exp["question"] and exp["category"] and exp["notes"]
        assert exp["manual_steps"]
        for arm in (exp["agent_arm"], exp["manual_arm"]):
            assert arm["output"] is not None, exp["task_id"]
            assert arm["output_hash"].startswith("0x")
            assert arm["seconds"] > 0
            assert set(arm["cost"]) == {"amount", "unit", "note"}
            assert arm["error"] is None
        assert exp["deltas"] == compare(load(EXPERIMENTS / f"{exp['task_id']}.json"))


def test_the_page_reaches_no_verdict(page):
    """A comparison of three recorded runs cannot support a claim about agents at
    large, so the words that make one are refused outright."""
    lowered = page.lower()
    for word in VERDICT_WORDS:
        assert word not in lowered, f"the advantage page reaches a verdict: {word!r}"


def test_the_page_states_the_security_task_as_a_loss(page):
    """The agent arm returned one of the four vectors the manual arm found. Deleting
    that from the page would leave three clean wins the evidence does not support, so
    the finding is pinned to the section that carries it."""
    security = section(page, "03-security")

    assert "SANITIZE" in security
    assert "BLOCK" in security
    assert "did not flag" in security
    assert "lost this task on substance" in security


def test_a_reader_meets_the_loss_in_the_summary_before_any_task_section(page):
    """Burying it under the per-task detail would be the same deletion, slower."""
    summary = page[: page.index('id="01-liquidity" aria-labelledby=')]

    assert "The agent arm lost this task on substance." in summary
    assert "did not flag the other three" in summary
    assert "not a saving on the question" in summary


def test_the_page_carries_every_recorded_figure_the_json_carries(page):
    """The drift guard. Re-derived from the experiment files with the same recipe that
    authored the page, so evidence edited without the page fails here."""
    for exp in experiments():
        deltas = compare(exp)
        assert html.escape(exp.question, quote=False) in page, exp.task_id
        assert f"{deltas['speedup']}x" in page, exp.task_id
        for arm, seconds in (
            (exp.agent_arm, deltas["seconds_agent"]),
            (exp.manual_arm, deltas["seconds_manual"]),
        ):
            rendered = json.dumps(arm["output"], indent=2, sort_keys=True, ensure_ascii=False)
            assert html.escape(rendered, quote=False) in page, f"{exp.task_id} {arm['name']}"
            assert f"{seconds:.2f} s" in page, f"{exp.task_id} {arm['name']}"
            assert arm["output_hash"] in page, f"{exp.task_id} {arm['name']}"
            cost = arm["cost"]
            assert html.escape(f"{cost['amount']} {cost['unit']}", quote=False) in page
            assert html.escape(cost["note"], quote=False) in page


def test_the_page_lets_a_reader_repeat_the_manual_arm(page):
    """A manual baseline nobody can repeat is a baseline nobody can contest. The
    ordinal moves into the list markup; every other word of the step is the recorded
    one."""
    for exp in experiments():
        block = section(page, exp.task_id)
        assert block.count("<li>") == len(exp.manual_steps), exp.task_id
        for step in exp.manual_steps:
            text = re.sub(r"^\d+\.\s+", "", step)
            assert html.escape(text, quote=False) in block, f"{exp.task_id}: {step[:40]}"


def test_the_page_prints_the_recorded_notes_including_the_qualified_results(page):
    for exp in experiments():
        block = section(page, exp.task_id)
        for paragraph in exp.notes.split("\n\n"):
            assert html.escape(paragraph, quote=False) in block, exp.task_id


def test_full_outputs_are_wrapped_rather_than_left_to_scroll_the_page(page):
    """Recorded outputs carry 66-character hashes and unbroken URLs, and `pre` does
    not wrap on its own."""
    assert page.count('<pre class="wrap-anywhere">') >= 2 * len(TASK_IDS)
    css = (Path(__file__).resolve().parents[1] / "docket" / "api" / "web" / "style.css").read_text(
        encoding="utf-8"
    )
    assert "white-space: pre-wrap" in css
    assert "list-style: decimal" in css


def test_both_paths_are_documented_for_the_agents_told_not_to_invent_endpoints(client):
    """`/advantage.json` is in the schema, so the existing llms.txt drift test already
    forces it there. `/advantage` is not, and a page nobody is told about is a page
    nobody reads — so both are asserted, in both documents."""
    assert "/advantage.json" in client.get("/openapi.json").json()["paths"]
    for name in ("llms.txt", "SKILL.md"):
        body = (STATIC_DIR / name).read_text(encoding="utf-8")
        assert "/advantage.json" in body, name
        assert "/advantage" in body, name
    assert client.get("/").json()["advantage"] == "/advantage.json"


def test_the_report_is_reachable_from_every_page_of_the_site(client):
    for path in ("/", "/browse", "/agent", "/advantage"):
        resp = client.get(path, headers={"accept": "text/html"})
        assert 'href="/advantage"' in resp.text, path
