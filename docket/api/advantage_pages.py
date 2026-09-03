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


# The three answers a cell may give when it has no number, and exactly what each means.
# A blank cell is read as a zero, and a dash is read as whichever of these the reader
# already believed, so the page says which one it is.
UNSCORED = "unscored"
NOT_RUN = "not run"
NOT_RECORDED = "not recorded"


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


def _cost_display(cost: dict) -> str:
    """One arm's recorded cost, in the asset name this page already uses for it.

    `$U` is the name the v1 records were written under; the page renders it as USDT
    everywhere else, and a second spelling of one asset on one page is a second asset as
    far as a reader can tell.
    """
    unit = "USDT" if cost["unit"] == "$U" else cost["unit"]
    return f"{cost['amount']} {unit}"


def _one_page_table(caption: str, rows: list[tuple[str, ...]]) -> str:
    headers = (
        "Task or family",
        "Arms",
        "n",
        "Time medians",
        "Out-of-pocket cost",
        "Objective quality",
        "State",
    )
    head = "".join(f'<th scope="col">{_esc(header)}</th>' for header in headers)
    body = "".join(
        '<tr><th scope="row" class="mono">'
        + _esc(row[0])
        + "</th>"
        + "".join(f"<td>{_esc(cell)}</td>" for cell in row[1:])
        + "</tr>"
        for row in rows
    )
    return (
        f'<div class="table-wrap"><table><caption>{_esc(caption)}</caption><thead><tr>'
        f"{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _v1_rows(experiments: list[dict]) -> list[tuple[str, ...]]:
    rows = []
    for experiment in experiments:
        deltas = experiment["deltas"]
        agent = experiment["agent_arm"]
        manual = experiment["manual_arm"]
        complete = agent.get("output") is not None and manual.get("output") is not None
        rows.append(
            (
                experiment["task_id"],
                "agent, manual",
                f"{1 if complete else 0} complete pair",
                f"agent {deltas['seconds_agent']} s · manual {deltas['seconds_manual']} s",
                f"agent {_cost_display(deltas['cost_agent'])} · "
                f"manual {_cost_display(deltas['cost_manual'])}",
                # v1 grades neither arm. That is a property of the protocol, not a
                # missing artifact, and it is the reason v2 and v3 exist.
                UNSCORED,
                "recorded" if complete else NOT_RUN,
            )
        )
    return rows


def _v2_figure(figure: dict | None) -> str:
    if not isinstance(figure, dict):
        return NOT_RECORDED
    name = figure.get("name", "figure")
    rate = figure.get("rate")
    distribution = figure.get("distribution")
    if isinstance(rate, dict):
        return f"{name} {rate['numerator']}/{rate['denominator']} ({rate['value']:.4f})"
    if isinstance(distribution, dict):
        return f"{name} median {distribution['median']:.4f} (n={distribution['n']})"
    if isinstance(figure.get("usd"), (int, float)):
        return f"{name} {figure['usd']:.4f} USD"
    return f"{name} {NOT_RECORDED}"


def _v2_rows(payload: dict) -> list[tuple[str, ...]]:
    rows = []
    for experiment in payload["experiments"]:
        spec = experiment["spec"]
        nulls = spec.get("null_baselines")
        falsifier = experiment.get("falsifier_result")
        rows.append(
            (
                experiment["experiment_id"],
                f"agent, {len(nulls) if isinstance(nulls, list) else 0} computed nulls",
                f"{spec['n_planned']} planned",
                # v2 registered no timing measure, so there is no median to publish.
                NOT_RECORDED,
                NOT_RECORDED,
                _v2_figure((experiment.get("headline") or {}).get("figure")),
                "refuted"
                if isinstance(falsifier, dict) and falsifier.get("refuted")
                else "not refuted",
            )
        )
    return rows


def _v3_rows(payload: dict) -> list[tuple[str, ...]]:
    rows = []
    for family in payload.get("families", []):
        spec = family["spec"]
        progress = family.get("run_progress")
        # An absent measure means one of two different things, and which one it is
        # depends on whether any primary ever became terminal. A registered family with
        # a ledger but no terminal primary has not run, whatever the ledger's shape.
        ran = isinstance(progress, dict) and progress["terminal_primaries"] > 0
        absent = UNSCORED if ran else NOT_RUN
        speed = family.get("speed")
        quality = family.get("quality")
        totals = (family.get("costs") or {}).get("totals") or []
        rows.append(
            (
                family["spec_id"],
                ", ".join(sorted(spec.get("arms") or {})) or NOT_RECORDED,
                f"{progress['terminal_primaries']}/{progress['scheduled_primaries']}"
                " primaries terminal"
                if isinstance(progress, dict)
                else f"0/{spec['n_planned']} planned pairs run",
                f"{speed['median_seconds_saved']} s median saving over "
                f"{speed['n_complete_pairs']} complete pairs"
                if isinstance(speed, dict)
                else absent,
                " · ".join(
                    f"{total['arm']} {total['amount']} {total['unit']}"
                    for total in totals
                )
                or absent,
                f"agent median {quality['arms']['agent']['median_total']} · "
                f"manual median {quality['arms']['manual']['median_total']}"
                if isinstance(quality, dict)
                else absent,
                family["state"],
            )
        )
    return rows


def advantage_one_page(
    shell: str, *, experiments: list[dict], advantage_v2: dict, advantage_v3: dict
) -> str:
    """Every registered task and family on one page, derived from the three reports.

    The three reports are additive and none supersedes another, so a reader who wants to
    know what has actually been measured has had to open all three and hold them side by
    side. This is that comparison, built from the same payloads the JSON routes return
    rather than transcribed from them, and carrying no figure the artifacts do not.
    """
    marker = "<!-- advantage-one-page -->"
    if marker not in shell:
        raise ValueError("advantage v1: one-page summary marker is missing")
    v3_body = (
        _one_page_table("V3 — pre-registered paired families.", _v3_rows(advantage_v3))
        if "error" not in advantage_v3
        else '<div class="notice notice-warn"><p>The v3 report could not be '
        "reconstructed at startup, so no family state is summarised here.</p></div>"
    )
    body = (
        '<section class="one-page" id="one-page" aria-labelledby="one-page-title">'
        '<h2 id="one-page-title">Agent Advantage, one page</h2>'
        '<p class="section-note">Every registered task and family across the three '
        "additive reports: the arms it ran, how many, the times and costs its records "
        "carry, its objective quality measure and its state. Every value is read from "
        'the artifacts. <span class="mono">unscored</span> means the required scoring '
        'artifacts are absent, <span class="mono">not run</span> means no primary became '
        'terminal, and <span class="mono">not recorded</span> means the protocol '
        "registered no such measure. Nothing here is an average over repeats.</p>"
        + _one_page_table(
            "V1 — paired agent-versus-person tasks, one observation each.",
            _v1_rows(experiments),
        )
        + _one_page_table(
            "V2 — agent versus computed nulls, no manual arm.", _v2_rows(advantage_v2)
        )
        + v3_body
        + "</section>"
    )
    return shell.replace(marker, body)


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
        "Each family has its own record and links "
        "to the underlying artifacts; those artifacts no longer arrive in one document.</p>"
        f'<div class="cards">{"".join(cards)}</div></section>'
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
    return fill(shell.replace(marker, v3_index(payload)), shallow)


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
            f"<dt>Outcomes</dt><dd>{_esc(outcomes)}</dd></dl></div>"
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
