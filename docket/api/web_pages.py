"""Server-rendered initial states for the judge-facing data pages."""

import html
from datetime import datetime, timezone

from ..marketplace.models import ServiceRecord


def _esc(value) -> str:
    return html.escape(str(value))


def _display_date(value) -> str:
    if not value or "T" not in str(value):
        return str(value or "—")
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def service_initial(record: ServiceRecord) -> str:
    metric = record.metrics[0] if record.metrics else None
    finding = (
        f"<strong>{_esc(metric.render())}</strong> — {_esc(metric.name.lower())}, "
        f"bounded to {_esc(metric.window)}."
        if metric is not None
        else "<strong>0 recorded measurements.</strong> No run is represented on this page."
    )
    metrics = "".join(
        '<div class="panel"><p class="metric-value">'
        f"{_esc(metric.render())}</p><p><strong>{_esc(metric.name)}</strong></p>"
        f'<p class="dim">{_esc(metric.method)}, observed {_esc(metric.observed_at)}; '
        f"{_esc(metric.window)}.</p></div>"
        for metric in record.metrics
    )
    evidence = (
        "".join(
            f'<li><a href="{_esc(reference.url)}">{_esc(reference.label)}</a></li>'
            for reference in record.evidence
        )
        or "<li>No recorded run is published for this service yet.</li>"
    )
    inputs = "".join(
        f'<dt><span class="mono">{_esc(name)}</span></dt><dd><strong>{_esc(field["type"])}</strong>'
        f"{' · required' if field.get('required') else ' · optional'}. "
        f"{_esc(field.get('description', 'No description supplied.'))}</dd>"
        for name, field in record.input_schema.items()
    )
    category = (
        f'<p><span class="badge">{_esc(record.category.value)}</span> — '
        "Docket's declaration about the service it runs.</p>"
        if record.category is not None
        else '<p><span class="badge">Outside the four job categories</span></p>'
    )
    return (
        f'<h1>{_esc(record.name)}</h1><p class="lede">{finding}</p>{category}'
        '<section aria-labelledby="service-offer-heading"><h2 id="service-offer-heading">'
        f"What arrives</h2><p>{_esc(record.what_you_get)}</p></section>"
        '<div class="panel"><dl class="deflist">'
        f'<dt>Typical run, declared</dt><dd class="num">{record.typical_seconds} seconds</dd>'
        f"<dt>Evidence modality</dt><dd>{_esc(record.evidence_modality.replace('_', ' '))}</dd>"
        f"<dt>What activating does</dt><dd>{_esc(record.activation_means)}</dd>"
        f'<dt>Agent call</dt><dd class="mono">POST /hire/{_esc(record.service_id)}</dd>'
        f"</dl></div>"
        '<section aria-labelledby="observed-heading"><h2 id="observed-heading">'
        'What has been observed of it</h2><p class="section-note">Single observations '
        f'from recorded runs, not averages.</p><div class="cards">{metrics}</div></section>'
        '<section aria-labelledby="evidence-heading"><h2 id="evidence-heading">'
        f'The record behind it</h2><ul class="facts">{evidence}</ul></section>'
        '<section aria-labelledby="inputs-heading"><h2 id="inputs-heading">What to send</h2>'
        f'<dl class="deflist panel">{inputs}</dl></section>'
        '<section aria-labelledby="limits-heading"><h2 id="limits-heading">What it cannot do</h2>'
        f'<div class="notice notice-warn"><p>{_esc(record.limitations)}</p></div></section>'
        '<section aria-labelledby="identity-heading"><h2 id="identity-heading">Its identity on chain</h2>'
        f'<div class="panel"><p>{_esc(record.identity_line)}</p></div></section>'
    )


def _pancake_record(history: dict) -> str:
    lines = [line for line in history["lines"] if isinstance(line, dict)]
    if not lines:
        return (
            '<div class="panel"><p><strong>0 stored rows are mounted on this host.</strong> '
            "No fixed-window owner decision is represented here.</p></div>"
        )
    rows = []
    for line in lines[-10:]:
        report = line.get("report") or {}
        position = (report.get("positions") or [{}])[0]
        diagnosis = position.get("diagnosis") or {}
        rows.append(
            "<tr>"
            f"<td>{_esc(_display_date(line.get('decided_at') or line.get('observed_at')))}</td>"
            f"<td>{_esc(line.get('kind') or 'observation')}</td>"
            f"<td>{_esc(line.get('decision') or diagnosis.get('decision') or line.get('error') or 'No decision sentence recorded.')}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><caption>Latest '
        f"{len(rows)} of {len(lines)} parsed rows from /lp-record. "
        f"{'The response was truncated.' if history['truncated'] else 'The response was not truncated.'}"
        '</caption><thead><tr><th scope="col">Date</th><th scope="col">Kind</th>'
        f'<th scope="col">Decision</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def pancake_initial(
    shell: str,
    service: ServiceRecord,
    history: dict,
    advantage_v2: dict,
    context: dict,
) -> str:
    impact = advantage_v2["decision_impact"]
    reversal = impact["ranking_reversals"]
    fixed = impact["dollars_at_notionals"]["notionals"][0]
    payback = impact["break_even_shift"]
    meta = context["subgraph_meta"]
    replacements = {
        "<!-- pancake-decision-initial -->": (
            '<div class="panel"><p><strong>No live position decision is embedded.</strong> '
            "JavaScript requests one fresh Range Doctor run when this page opens; the "
            "server-rendered evidence below is available before that run.</p>"
            f'<p class="dim">{_esc(service.what_you_get)}</p></div>'
        ),
        "<!-- pancake-record-initial -->": _pancake_record(history),
        "<!-- pancake-economics-initial -->": (
            '<div class="panel"><p>The fresh run supplies gross and protocol-adjusted APR, '
            "caller-declared fixed-notional dollars, and cost-only recenter payback. None is "
            "copied into this initial page because the position and block are live inputs.</p>"
            f'<p class="dim">{_esc(service.limitations)}</p></div>'
        ),
        "<!-- pancake-actions-initial -->": (
            '<div class="panel"><p>Wait-versus-recenter conditions appear only after the fresh '
            "read. Any resulting PancakeSwap link opens a planner; Docket neither signs nor "
            "submits a transaction.</p></div>"
        ),
        "<!-- pancake-impact-initial -->": (
            '<div class="impact-grid"><article class="impact-stat"><p class="metric-label">'
            f'Annual overstatement</p><p class="metric-value">${fixed["median_annual_overstatement_usd"]:,.2f}</p>'
            f'<p class="metric-note">Median at ${fixed["notional_usd"]:,.0f} fixed notional (n={fixed["n_pools"]}).</p></article>'
            '<article class="impact-stat"><p class="metric-label">Payback delay</p>'
            f'<p class="metric-value">{payback["median_days_later_than_gross_implies"]:.2f} days</p>'
            f'<p class="metric-note">Median across {payback["n_moves"]} candidate moves.</p></article>'
            '<article class="impact-stat"><p class="metric-label">Ranking reversals</p>'
            f'<p class="metric-value">{reversal["numerator"]}/{reversal["denominator"]}</p>'
            '<p class="metric-note">Ordered eligible-pool pairs in the frozen corpus.</p></article></div>'
            f'<div class="notice"><p><strong>post-hoc</strong> — {_esc(impact["registration_note"])}</p>'
            f'<p class="dim">{_esc(reversal["what_this_measures"])}</p></div>'
        ),
        "<!-- pancake-context-initial -->": (
            f"<p>{_esc(context['first_party_skills'])}</p><p>On {_esc(meta['query_observed_at'])}, "
            f'the subgraph reported indexed time <span class="mono">{_esc(meta["indexed_at"])}</span> '
            f'and <span class="mono">hasIndexingErrors: {_esc(str(meta["has_indexing_errors"]).lower())}</span>.</p>'
            f'<p class="dim">{_esc(meta["method"])}</p>'
        ),
    }
    rendered = shell
    for marker, body in replacements.items():
        if marker not in rendered:
            raise ValueError(f"pancake page carries no {marker}")
        rendered = rendered.replace(marker, body)
    return rendered


def stats_page(shell: str, stats) -> str:
    coverage = stats.coverage
    registry_total = (
        "unavailable"
        if stats.registry_total is None
        else f"at least {stats.registry_total:,}"
    )
    rows = (
        ("Snapshot", coverage.snapshot_id),
        (
            "Captured",
            _display_date(coverage.captured_at)
            if coverage.captured_at
            else "not recorded",
        ),
        ("Agents sampled", f"{coverage.sampled:,} of {coverage.expected:,}"),
        ("Snapshot complete", "yes" if coverage.complete else "no"),
        ("Registry scale measured", registry_total),
        ("Agents with feedback", f"{stats.with_feedback:,}"),
        ("Agents declaring a callable endpoint", f"{stats.callable_declared:,}"),
        ("Endpoints evaluated", f"{stats.endpoints_evaluated:,}"),
        ("Endpoints attempted", f"{stats.endpoints_attempted:,}"),
        ("Endpoints responded", f"{stats.endpoints_responded:,}"),
        ("Blocked by policy", f"{stats.blocked_by_policy:,}"),
        ("Unresolved", f"{stats.unresolved:,}"),
    )
    table_rows = "".join(
        f'<tr><th scope="row">{_esc(label)}</th><td class="num">{_esc(value)}</td></tr>'
        for label, value in rows
    )
    families = "".join(
        f'<tr><th scope="row" class="mono">{_esc(row["name_family"])}</th>'
        f'<td class="num">{row["count"]:,}</td><td class="num">{row["share_pct"]:.1f}%</td></tr>'
        for row in stats.top_name_families
    )
    body = (
        '<section class="hero"><h1>Registry coverage</h1><p class="lede"><strong>'
        f"{coverage.sampled:,} of {coverage.expected:,} agents sampled</strong> in snapshot "
        f"{coverage.snapshot_id}; complete means complete for the recorded population "
        f'<span class="mono">{_esc(coverage.population or "unspecified")}</span>, not necessarily the chain.</p></section>'
        '<section aria-labelledby="coverage-heading"><h2 id="coverage-heading">What this snapshot contains</h2>'
        '<div class="table-wrap"><table class="stats-table"><caption>Counts from one served snapshot; registry scale is a lower bound.</caption>'
        f"<tbody>{table_rows}</tbody></table></div></section>"
        '<section aria-labelledby="families-heading"><h2 id="families-heading">Largest self-declared name families</h2>'
        '<p class="section-note">The first word of each agent-chosen name; not verified deployer provenance.</p>'
        '<div class="table-wrap"><table class="stats-table"><thead><tr><th scope="col">Name family</th>'
        f'<th scope="col">Agents</th><th scope="col">Share</th></tr></thead><tbody>{families}</tbody></table></div></section>'
        '<section aria-labelledby="probe-heading"><h2 id="probe-heading">Probe method</h2>'
        f'<div class="panel"><p>{_esc(stats.probe_method)}</p></div></section>'
    )
    marker = "<!-- stats-content -->"
    if marker not in shell:
        raise ValueError("stats page has no content marker")
    return shell.replace(marker, body)
