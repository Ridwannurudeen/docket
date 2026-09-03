"""Summary and depth views over the immutable advantage records."""

import html
import json
import re

from ..advantage.v3.page import STATE_TEXT

V1_TASK_IDS = ("01-liquidity", "02-trading", "03-security")
V3_TOPICS = {
    "registration": ("spec", "Registered specification"),
    "inputs": ("inputs", "Locked inputs"),
    "calibration": ("calibration", "Evaluator calibration"),
    "ledger": ("ledger", "Claim-once ledger"),
    "blinded-outputs": ("blinded_bundle", "Prompt-blinded outputs"),
    "score-sheets": ("score_sheets", "Published score sheets"),
    "mapping": ("mapping", "Published A/B mapping"),
    "quality": ("quality", "Rubric aggregates"),
    "speed": ("speed", "Paired speed measures"),
    "costs": ("costs", "Recorded costs"),
    "formula-metrics": ("formula_metrics", "Family-specific formula measures"),
    "falsifier": ("falsifier_result", "Registered falsifier checks"),
}


def _esc(value) -> str:
    return html.escape(str(value))


def _v1_block(shell: str, task_id: str) -> tuple[int, int, str]:
    start = shell.index(f'        <section id="{task_id}"')
    end = shell.index("        </section>", start) + len("        </section>")
    return start, end, shell[start:end]


def v1_page(shell: str, task_id: str | None = None) -> str:
    if task_id is not None and task_id not in V1_TASK_IDS:
        raise KeyError(task_id)
    blocks = {current: _v1_block(shell, current) for current in V1_TASK_IDS}
    rendered = shell
    for current in reversed(V1_TASK_IDS):
        start, end, block = blocks[current]
        if current != task_id:
            rendered = rendered[:start] + rendered[end:]
            continue
        block = block.replace(
            f'id="{current}" aria-labelledby=',
            f'id="{current}-record" aria-labelledby=',
            1,
        )
        block = block.replace(
            '<details class="evidence-details">', '<div class="evidence-record">', 1
        )
        block = re.sub(r"<summary>.*?</summary>", "", block, count=1, flags=re.DOTALL)
        closing = block.rfind("</details>")
        if closing == -1:
            raise ValueError(
                f"{current}: evidence record has no closing details element"
            )
        block = block[:closing] + "</div>" + block[closing + len("</details>") :]
        rendered = rendered[:start] + block + rendered[end:]
    return rendered


def v3_index(payload: dict) -> str:
    cards = []
    for family in payload["families"]:
        spec_id = _esc(family["spec_id"])
        progress = family.get("run_progress")
        progress_text = ""
        if progress is not None:
            progress_text = (
                f'<p><span class="num">{_esc(progress["terminal_primaries"])}</span> of '
                f'<span class="num">{_esc(progress["scheduled_primaries"])}</span> '
                "scheduled primaries reached a terminal ledger event.</p>"
            )
        cards.append(
            f'<article class="panel" id="{spec_id}"><h3><a href="/advantage/v3/{spec_id}">'
            f"{spec_id}</a></h3>"
            '<p class="status-line"><span class="status-key">State</span>'
            f'<span class="mono">{_esc(family["state"])}</span></p>'
            f"<p>{_esc(STATE_TEXT[family['state']])}</p>"
            f"<p>{_esc(family['spec']['question'])}</p>{progress_text}"
            f'<p><a href="/advantage/v3/{spec_id}">Read this family</a></p></article>'
        )
    return (
        '<section aria-labelledby="v3-families"><h2 id="v3-families">'
        f'{len(payload["families"])} registered families</h2><p class="section-note">'
        'Each family has its own record and links '
        "to the underlying artifacts; those artifacts no longer arrive in one document.</p>"
        f'<div class="cards">{"".join(cards)}</div></section>'
    )


def _cell(value) -> str:
    """One table cell: a number as a number, an absent figure as an em dash."""
    if value is None:
        return '<span class="mono">&mdash;</span>'
    if isinstance(value, float):
        return f'<span class="num">{_esc(round(value, 3))}</span>'
    if isinstance(value, int) and not isinstance(value, bool):
        return f'<span class="num">{_esc(value)}</span>'
    return _esc(value)


def _cost_cell(costs: dict, arms) -> str:
    parts = []
    for arm in arms:
        cost = costs.get(arm)
        if not isinstance(cost, dict):
            parts.append(f"{_esc(arm)}: &mdash;")
            continue
        amount = f'{cost.get("amount", "")} {cost.get("unit", "")}'.strip()
        parts.append(f'{_esc(arm)}: <span class="mono">{_esc(amount)}</span>')
    return "<br>".join(parts) if parts else '<span class="mono">&mdash;</span>'


def _quality_cell(row: dict) -> str:
    parts = []
    for arm in row["arms"]:
        value = row["quality_by_arm"].get(arm)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parts.append(f'{_esc(arm)}: <span class="num">{_esc(round(value, 3))}</span>')
        else:
            parts.append(f"{_esc(arm)}: &mdash;")
    measure = row["quality_measure"]
    if measure:
        parts.append(f'<span class="section-note">{_esc(measure)}</span>')
    return "<br>".join(parts) if parts else '<span class="mono">&mdash;</span>'


def _one_page_section(one_page: dict) -> str:
    rows = []
    for row in one_page["rows"]:
        planned = _cell(row["n_planned"])
        terminal = _cell(row["n_terminal"])
        reasons = "".join(
            f'<p class="section-note">{_esc(field)}: {_esc(reason)}</p>'
            for field, reason in sorted(row["unavailable"].items())
        )
        rows.append(
            "<tr>"
            f'<th scope="row"><span class="mono">{_esc(row["task"])}</span></th>'
            f'<td><span class="mono">{_esc(row["version"])}</span></td>'
            f"<td>{_esc(row['category'])}</td>"
            f"<td>{_esc(', '.join(row['arms'])) or '&mdash;'}</td>"
            f"<td>{planned} / {terminal}</td>"
            f"<td>{_cell(row['median_agent_seconds'])}</td>"
            f"<td>{_cell(row['median_manual_seconds'])}</td>"
            f"<td>{_cost_cell(row['cost_by_arm'], row['arms'])}</td>"
            f"<td>{_quality_cell(row)}</td>"
            f'<td><span class="mono">{_esc(row["state"])}</span>{reasons}</td>'
            "</tr>"
        )
    headers = (
        "Task",
        "Report",
        "Category",
        "Arms",
        "Planned / terminal",
        "Median agent seconds",
        "Median manual seconds",
        "Out-of-pocket per arm",
        "Objective quality per arm",
        "State",
    )
    heading = "".join(f'<th scope="col">{_esc(label)}</th>' for label in headers)
    return (
        '<section aria-labelledby="one-page"><h2 id="one-page">'
        "Every registered task on one page</h2>"
        f'<p class="lede"><span class="num">{_esc(one_page["n_rows"])}</span> rows, every '
        "figure read out of a committed artifact at startup.</p>"
        f'<p class="section-note">{_esc(one_page["note"])}</p>'
        '<div class="table-wrap"><table><caption>'
        "Registered tasks across all three reports, with the reason beside every figure an "
        "artifact does not carry."
        f"</caption><thead><tr>{heading}</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div></section>"
    )


def v3_landing(shell: str, payload: dict) -> str:
    if "error" in payload:
        from ..advantage.v3.page import fill

        return fill(shell, payload)
    marker = "<!-- v3-family-index -->"
    if marker not in shell:
        raise ValueError("advantage v3: family index marker is missing")
    from ..advantage.v3.page import fill

    shallow = {**payload, "families": []}
    one_page = payload["summary"].get("one_page")
    index = v3_index(payload)
    if one_page is not None:
        # First of the generated sections, above the family index and the state summary.
        # The shell above the marker is Lane A's; nothing here edits it.
        index = _one_page_section(one_page) + index
    return fill(shell.replace(marker, index), shallow)


def _depth_shell(shell: str, title: str, body: str) -> str:
    rendered = re.sub(
        r"<title>.*?</title>", f"<title>{_esc(title)} — Docket</title>", shell, count=1
    )
    replacement = f'<main id="main"><div class="wrap">{body}</div></main>'
    return re.sub(
        r'<main id="main">.*?</main>', replacement, rendered, count=1, flags=re.DOTALL
    )


def v3_family_page(shell: str, family: dict) -> str:
    spec_id = _esc(family["spec_id"])
    spec = family["spec"]
    progress = family.get("run_progress")
    progress_html = ""
    if progress is not None:
        outcomes = (
            "; ".join(
                f"{count} {outcome.replace('_', ' ')}"
                for outcome, count in sorted(progress["outcomes"].items())
            )
            or "No terminal outcomes."
        )
        progress_html = (
            '<div class="panel"><h2>Run progress</h2><dl class="deflist">'
            f'<dt>Scheduled primaries</dt><dd class="num">{_esc(progress["scheduled_primaries"])}</dd>'
            f'<dt>Claimed primaries</dt><dd class="num">{_esc(progress["claimed_primaries"])}</dd>'
            f'<dt>Terminal primaries</dt><dd class="num">{_esc(progress["terminal_primaries"])}</dd>'
            f'<dt>Outcomes</dt><dd>{_esc(outcomes)}</dd></dl></div>'
        )
    links = []
    for slug, (field, label) in V3_TOPICS.items():
        if family.get(field) not in (None, [], {}):
            links.append(
                f'<li><a href="/advantage/v3/{spec_id}/{slug}">{_esc(label)}</a></li>'
            )
    unscored = (
        '<p class="status-line"><span class="status-key">Unscored reason</span>'
        f'<span class="mono">{_esc(family["unscored_reason"])}</span></p>'
        if family.get("unscored_reason")
        else ""
    )
    body = (
        '<p><a href="/advantage/v3">← All v3 families</a></p>'
        f'<section class="hero"><h1>{spec_id}</h1><p class="lede">{_esc(spec["question"])}</p>'
        '<p class="status-line"><span class="status-key">State</span>'
        f'<span class="mono">{_esc(family["state"])}</span>'
        f"<span>{_esc(STATE_TEXT[family['state']])}</span></p>{unscored}</section>"
        '<section aria-labelledby="registered-boundary"><h2 id="registered-boundary">Registered boundary</h2>'
        '<dl class="deflist panel">'
        f"<dt>Claim</dt><dd>{_esc(spec['claim'])}</dd>"
        f"<dt>Falsifier</dt><dd>{_esc(spec['falsifier'])}</dd>"
        f'<dt>Pairs planned</dt><dd class="num">{_esc(spec["n_planned"])}</dd>'
        f"<dt>Stopping rule</dt><dd>{_esc(spec['stopping_rule'])}</dd></dl></section>"
        f'{progress_html}<section aria-labelledby="family-artifacts"><h2 id="family-artifacts">'
        f'Family record</h2><ul class="link-list">{"".join(links)}</ul></section>'
    )
    return _depth_shell(shell, family["spec_id"], body)


def v3_topic_page(shell: str, family: dict, topic: str) -> str:
    if topic not in V3_TOPICS:
        raise KeyError(topic)
    field, label = V3_TOPICS[topic]
    value = family.get(field)
    if value in (None, [], {}):
        raise KeyError(topic)
    spec_id = _esc(family["spec_id"])
    record = html.escape(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False), quote=False
    )
    body = (
        f'<p><a href="/advantage/v3/{spec_id}">← {spec_id}</a></p>'
        f'<section class="hero"><h1>{_esc(label)}</h1><p class="lede">'
        f'The complete <span class="mono">{_esc(field)}</span> artifact for {spec_id}.</p></section>'
        f'<pre class="mono wrap-anywhere">{record}</pre>'
    )
    return _depth_shell(shell, f"{family['spec_id']} — {label}", body)
