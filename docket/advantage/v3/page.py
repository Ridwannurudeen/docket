"""Render v3 from the same report object returned by the JSON route.

The authored shell carries method and navigation prose. Every state, family, count and
artifact shown inside the report comes from the payload passed to ``fill``. Values are
escaped at the rendering boundary because later run records can contain arbitrary output.
"""

import html
import json

from . import report as report_module

MARKER = "<!-- v3-records -->"

STATE_TEXT = {
    report_module.REGISTERED_WAITING: "No input artifact is locked. No arm has run.",
    report_module.SUPERSEDED_BEFORE_INPUT_LOCK: (
        "A later pilot-informed registration superseded this unlocked family. No arm ran."
    ),
    report_module.ABANDONED_AFTER_FAILED_PRIMARY: (
        "A primary failed under the no-retry rule. Its ledger remains published, and a "
        "distinct successor does not replace or relabel it."
    ),
    report_module.LOCKED_NOT_RUN: "Inputs are locked. No primary attempt has been claimed.",
    report_module.RUNNING: (
        "The claim-once ledger has claimed work without a terminal event. Expired "
        "deadlines are shown as stale; this report does not repair the ledger."
    ),
    report_module.COMPLETE_UNSCORED: (
        "Every scheduled primary has a terminal ledger event; required scoring artifacts "
        "are absent, so rubric quality and the registered falsifier remain unavailable."
    ),
    report_module.REFUTED: (
        "At least one registered falsifier check fired; the registered claim is refuted."
    ),
    report_module.NOT_REFUTED: (
        "No registered falsifier check fired. This state is bounded to the registered claim."
    ),
}


def _esc(value) -> str:
    return html.escape(str(value))


def _row(cells, *, header=None) -> str:
    heading = f'<th scope="row">{header}</th>' if header is not None else ""
    return "<tr>" + heading + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


def _table(caption: str, headers, rows) -> str:
    heading = "".join(f'<th scope="col">{_esc(label)}</th>' for label in headers)
    return (
        '<div class="table-wrap"><table><caption>'
        + _esc(caption)
        + f"</caption><thead><tr>{heading}</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _json_record(title: str, value) -> str:
    body = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
    return (
        '<details class="raw"><summary>'
        + _esc(title)
        + '</summary><pre class="mono wrap-anywhere">'
        + _esc(body)
        + "</pre></details>"
    )


def _state_summary(payload: dict) -> str:
    summary = payload["summary"]
    rows = [
        _row(
            (
                f'<span class="num">{_esc(summary["states"].get(state, 0))}</span>',
                _esc(STATE_TEXT[state]),
            ),
            header=f'<span class="mono">{_esc(state)}</span>',
        )
        for state in payload["states"]
    ]
    return (
        '<section aria-labelledby="v3-summary"><h2 id="v3-summary">Current report state</h2>'
        f'<p class="lede"><span class="num">{_esc(summary["n_families"])}</span> registered '
        "families are reconstructed from the artifacts available when this process starts.</p>"
        + _table(
            "Every state in the closed vocabulary, including zero-count states.",
            ("State", "Families", "Meaning"),
            rows,
        )
        + "</section>"
    )


def _registration(spec: dict) -> str:
    input_hash = spec["inputs_sha256"] or "not locked"
    return (
        '<div class="panel"><h3>Registered question and boundary</h3>'
        '<dl class="deflist">'
        f"<dt>Question</dt><dd>{_esc(spec['question'])}</dd>"
        f"<dt>Category</dt><dd>{_esc(spec['category'])}</dd>"
        f"<dt>Claim</dt><dd>{_esc(spec['claim'])}</dd>"
        f"<dt>Falsifier</dt><dd>{_esc(spec['falsifier'])}</dd>"
        f'<dt>Pairs planned</dt><dd class="num">{_esc(spec["n_planned"])}</dd>'
        f"<dt>Stopping rule</dt><dd>{_esc(spec['stopping_rule'])}</dd>"
        f'<dt>Input reference</dt><dd class="mono wrap-anywhere">{_esc(spec["inputs_ref"])}</dd>'
        f'<dt>Input SHA-256</dt><dd class="mono wrap-anywhere">{_esc(input_hash)}</dd>'
        "<dt>Stage-one protocol hash</dt>"
        f'<dd class="mono wrap-anywhere">{_esc(spec["stage_one_protocol_hash"])}</dd>'
        f'<dt>Specification hash</dt><dd class="mono wrap-anywhere">{_esc(spec["spec_hash"])}</dd>'
        f"<dt>Registration witness</dt><dd>{_esc(spec['registration_provenance'])}</dd>"
        "</dl></div>"
    )


def _arms(spec: dict) -> str:
    cards = []
    for arm_name in ("manual", "agent"):
        arm = spec["arms"][arm_name]
        display_name = arm.get("display_name", arm_name.title())
        cards.append(
            '<div class="panel">'
            f'<h3>{_esc(display_name)} arm</h3><dl class="deflist">'
            f"<dt>What it does</dt><dd>{_esc(arm['what_it_does'])}</dd>"
            f"<dt>Who runs it</dt><dd>{_esc(arm['who_runs_it'])}</dd>"
            f"<dt>What is recorded</dt><dd>{_esc(arm['what_is_recorded'])}</dd>"
            "</dl></div>"
        )
    return '<div class="cards">' + "".join(cards) + "</div>"


def _progress(family: dict) -> str:
    progress = family["run_progress"]
    if progress is None:
        return ""
    stale = progress.get("stale_primaries", [])
    return (
        '<div class="panel"><h3>Ledger progress</h3><dl class="deflist">'
        f'<dt>Scheduled primaries</dt><dd class="num">{_esc(progress["scheduled_primaries"])}</dd>'
        f'<dt>Claimed primaries</dt><dd class="num">{_esc(progress["claimed_primaries"])}</dd>'
        f'<dt>Terminal primaries</dt><dd class="num">{_esc(progress["terminal_primaries"])}</dd>'
        f'<dt>Terminal outcomes</dt><dd class="mono">{_esc(progress["outcomes"])}</dd>'
        f'<dt>Stale claimed primaries</dt><dd class="num">{_esc(len(stale))}</dd>'
        "</dl>"
        + (
            _json_record(
                "Claimed primaries past deadline with no terminal event",
                stale,
            )
            if stale
            else ""
        )
        + "</div>"
    )


def _artifacts(family: dict) -> str:
    fields = (
        ("inputs", "Locked input envelope"),
        ("calibration", "Evaluator calibration checks"),
        ("ledger", "Append-only ledger events"),
        ("blinded_bundle", "Prompt-blinded output bundle"),
        ("score_sheets", "Published model-seat sheets"),
        ("mapping", "Published A/B mapping"),
        ("quality", "Rubric aggregates"),
        ("speed", "Paired speed measures"),
        ("costs", "Recorded costs"),
        ("formula_metrics", "Family-specific formula measures"),
        ("falsifier_result", "Registered falsifier checks"),
    )
    records = [
        _json_record(title, family[field])
        for field, title in fields
        if family.get(field) not in (None, [], {})
    ]
    if family.get("unscored_reason"):
        records.insert(
            0,
            '<p class="status-line"><span class="status-key">Unscored reason</span>'
            f'<span class="mono">{_esc(family["unscored_reason"])}</span></p>',
        )
    return "".join(records)


def _family(family: dict) -> str:
    spec = family["spec"]
    family_id = _esc(family["spec_id"])
    state = family["state"]
    superseded = (
        '<p class="status-line"><span class="status-key">Superseded by</span>'
        f'<span class="mono">{_esc(family["superseded_by"])}</span></p>'
        if family.get("superseded_by")
        else ""
    )
    pilot = (
        _json_record("Registered pilot provenance", spec["pilot_provenance"])
        if spec.get("pilot_provenance") is not None
        else ""
    )
    return (
        f'<section id="{family_id}" aria-labelledby="{family_id}-heading">'
        f'<h2 id="{family_id}-heading">{family_id}</h2>'
        '<p class="status-line"><span class="status-key">State</span>'
        f'<span class="mono">{_esc(state)}</span><span>{_esc(STATE_TEXT[state])}</span></p>'
        + superseded
        + _registration(spec)
        + _arms(spec)
        + _progress(family)
        + _json_record("Registered execution protocol", spec["execution_protocol"])
        + _json_record("Registered evaluation protocol", spec["scoring"])
        + pilot
        + _artifacts(family)
        + "</section>"
    )


def _failure(payload: dict) -> str:
    error = payload["error"]
    return (
        '<section aria-labelledby="v3-unavailable"><h2 id="v3-unavailable">'
        "V3 report unavailable</h2>"
        '<p class="status-line"><span class="status-key">Error</span>'
        f'<span class="mono">{_esc(error["code"])}</span></p>'
        f'<p class="lede">{_esc(error["message"])}</p>'
        "<p>No family state is shown because reconstruction failed; an empty family list "
        "would falsely describe the evidence as absent.</p></section>"
    )


def render(payload: dict) -> str:
    """Render the summary and all families from one already-built report payload."""
    if "error" in payload:
        return _failure(payload)
    return _state_summary(payload) + "".join(
        _family(family) for family in payload["families"]
    )


def fill(shell: str, payload: dict) -> str:
    """Insert the report or refuse a shell that has no insertion boundary."""
    if MARKER not in shell:
        raise ValueError(
            f"advantage v3: the page shell carries no {MARKER}; the records have nowhere to go"
        )
    return shell.replace(MARKER, render(payload))
