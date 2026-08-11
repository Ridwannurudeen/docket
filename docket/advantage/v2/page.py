"""The v2 report as HTML, rendered from the same payload the JSON route serves.

The page and the JSON cannot disagree, because there is only one of them. v1's page is
authored markup guarded by a drift test that re-derives every figure from the experiment
files — a test that catches drift after it has been written. Here the drift is unavailable:
`render` takes `report.report()` and nothing else, so a figure on the page is the figure in
the document by construction, and the authored half of the page holds no numbers at all.

What the page shows that an aggregate would not: every pool row behind the two liquidity
distributions, every one of the 141 security scans including the nine that failed, and every
trigger the replay fired. Failures are rendered in their place in the denominator rather than
filtered out, which is the whole reason they were retained.

Everything from a record is escaped on the way out. Most of it is prose this repository wrote,
but the security corpus is 47 hand-authored hostile payloads and the scan outputs quote them
back — text written to be acted on by whatever reads it. It is rendered as text, always.
"""

import html

# Two payloads whose texts differ in exactly one byte, and whose verdicts differ. It is the
# corpus's sharpest single claim, so the page prints both in full rather than leaving a reader
# to reconstruct them from a file — with the newline made visible, since the whole finding is
# a character that is otherwise invisible.
MINIMAL_PAIR = ("minimal-pair-space-joined", "minimal-pair-newline-joined")

# Where the authored shell hands over to the records. The shell holds the prose and not one
# figure; everything a reader could quote is rendered from the payload the JSON route serves.
MARKER = "<!-- v2-records -->"


def _esc(value) -> str:
    return html.escape(str(value))


def _rate(rate: dict) -> str:
    """A rate as its two counts first, with the share after them and never instead of them."""
    if rate["value"] is None:
        return f"{rate['numerator']} of {rate['denominator']} (no observations to divide by)"
    return f"{rate['numerator']} of {rate['denominator']} ({rate['value'] * 100:.1f}%)"


def _distribution(dist: dict, *, unit: str = "") -> str:
    if not dist["n"]:
        return f"n={dist['n']}, nothing observed"
    suffix = f" {unit}" if unit else ""
    return (
        f"n={dist['n']}, min {dist['min']:.6g}{suffix}, median {dist['median']:.6g}{suffix}, "
        f"max {dist['max']:.6g}{suffix}"
    )


def _row(cells, *, header=None) -> str:
    head = f'<th scope="row">{header}</th>' if header is not None else ""
    return "<tr>" + head + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


def _table(caption: str, headers, rows) -> str:
    head = "".join(f'<th scope="col">{_esc(header)}</th>' for header in headers)
    return (
        '<div class="table-wrap"><table><caption>'
        + _esc(caption)
        + f"</caption><thead><tr>{head}</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _falsifier(result: dict) -> str:
    """The registered falsifier's clauses and what each one observed.

    The word for a clause that fired is "refuted" and the word for one that did not is
    "survived". Neither is a verdict about an agent: both are statements about one registered
    sentence and the figures it was checked against.
    """
    rows = [
        _row(
            (
                "refuted" if check["refuted"] else "survived",
                _esc(check["observed"]),
            ),
            header=f'<span class="mono">{_esc(check["clause"])}</span>',
        )
        for check in result["checks"]
    ]
    verdict = (
        "The claim is refuted: at least one clause of its own falsifier fired."
        if result["refuted"]
        else "No clause of the registered falsifier fired."
    )
    return f'<p class="section-note">{_esc(verdict)}</p>' + _table(
        "The registered falsifier, evaluated clause by clause against the measured figures.",
        ("Clause", "Result", "What was observed"),
        rows,
    )


def _headline(headline: dict) -> str:
    nulls = "".join(
        f"<dt>{_esc(null['name'])}</dt><dd>{_esc(_null_figure(null['figure']))}</dd>"
        for null in headline["nulls"]
    )
    return (
        f'<p class="lede">{_esc(headline["statement"])}</p>'
        '<div class="panel"><h4>Margin over the null</h4>'
        f"<p>{_esc(headline['margin']['statement'])}</p></div>"
        '<div class="panel"><h4>The nulls, computed over the same data</h4>'
        f'<dl class="deflist">{nulls}</dl></div>'
    )


def _null_figure(figure: dict) -> str:
    if "rate" in figure:
        return _rate(figure["rate"])
    if "distribution" in figure:
        return _distribution(figure["distribution"])
    return str(figure.get("value"))


def _registration(spec: dict) -> str:
    """What was written down before the run, including the sentence that would refute it."""
    return (
        '<div class="panel"><h4>The pre-registration</h4>'
        f'<dl class="deflist">'
        f"<dt>Claim</dt><dd>{_esc(spec['claim'])}</dd>"
        f"<dt>Falsifier</dt><dd>{_esc(spec['falsifier'])}</dd>"
        f'<dt>Metric</dt><dd><span class="mono">{_esc(spec["metric"]["name"])}</span>, in '
        f"{_esc(spec['metric'].get('units', ''))}. {_esc(spec['metric']['formula'])}</dd>"
        f"<dt>Runs planned</dt><dd>{_esc(spec['n_planned'])}</dd>"
        f"<dt>Stopping rule</dt><dd>{_esc(spec['stopping_rule'])}</dd>"
        f'<dt>Dataset</dt><dd><span class="mono">{_esc(spec["dataset_ref"])}</span>, '
        f'sha256 <span class="mono">{_esc(spec["dataset_sha256"])}</span></dd>'
        f"<dt>Registered</dt><dd>{_esc(spec['registered_at'])}, hashed to "
        f'<span class="mono">{_esc(spec["spec_hash"])}</span></dd>'
        "</dl></div>"
    )


def _pool_rows(run: dict) -> str:
    rows = [
        _row(
            (
                _esc(pool["fee_tier"]),
                f'{_esc(pool["displayed"]["tvlUSD"])} <span class="dim">'
                f"({pool['raw']['tvlUSD']:,.2f})</span>",
                f'{_esc(pool["displayed"]["feeUSD24h"])} <span class="dim">'
                f"({pool['raw']['feeUSD24h']:,.2f})</span>",
                f"{pool['net_fee_apr'] * 100:.4f}%",
                f"{pool['ui_rounded_net_fee_apr'] * 100:.4f}%",
                f"{pool['gross_fee_apr'] * 100:.4f}%",
                f"{pool['rounding_gap_pp']:+.6f}",
                f"{pool['gross_gap_pp']:+.4f}",
            ),
            header=_esc(pool["pair"]),
        )
        for pool in run["pools"]
    ]
    return _table(
        f"All {len(run['pools'])} eligible pools in the registered snapshot — every row behind "
        "the two distributions above, with the displayed figure beside the raw one it rounds.",
        (
            "Pair",
            "Fee tier",
            "TVL (displayed / raw)",
            "Fees 24h (displayed / raw)",
            "Net",
            "Net from displayed",
            "Gross",
            "Rounding gap (pp)",
            "Gross gap (pp)",
        ),
        rows,
    )


def _pass_cell(trial: dict) -> str:
    if trial["error"] is not None:
        return f'<span class="mono">failed</span> {_esc(trial["error"])}'
    body = trial["output"]
    body = body.get("result", body)
    classes = ", ".join(sorted(body["threat_classes"])) or "no classes named"
    return f'<span class="mono">{_esc(body["verdict"])}</span> — {_esc(classes)}'


def _payload_rows(experiment: dict) -> str:
    labels = {payload["payload_id"]: payload for payload in experiment["dataset"]["payloads"]}
    rows = []
    for entry in experiment["run"]["payloads"]:
        payload = labels[entry["arm_name"]]
        cells = [_esc(", ".join(payload["labels"]) or "benign control")]
        cells += [_pass_cell(trial) for trial in entry["trials"]]
        cells.append(_esc(sum(trial["attempts"] for trial in entry["trials"])))
        rows.append(_row(cells, header=f'<span class="mono">{_esc(entry["arm_name"])}</span>'))
    counts = experiment["scores"]["warden"]["counts"]
    return _table(
        f"All {counts['n_payloads']} payloads, three passes each — {len(rows) * 3} scans, of "
        f"which {counts['n_failed_scans']} failed. A failed scan is shown where it happened and "
        "counted as a failed trial, never as a detection miss.",
        ("Payload", "Labelled", "Pass 1", "Pass 2", "Pass 3", "HTTP attempts"),
        rows,
    )


def _minimal_pair(experiment: dict) -> str:
    """The two payloads that differ by one byte, printed with the byte made visible."""
    payloads = {payload["payload_id"]: payload for payload in experiment["dataset"]["payloads"]}
    scored = {entry["arm_name"]: entry for entry in experiment["run"]["payloads"]}
    blocks = []
    for payload_id in MINIMAL_PAIR:
        payload = payloads[payload_id]
        text = payload["text"].replace("\n", "↵\n")
        verdicts = " / ".join(_pass_cell(trial) for trial in scored[payload_id]["trials"])
        blocks.append(
            f'<dt><span class="mono">{_esc(payload_id)}</span></dt>'
            f'<dd><pre class="mono">{_esc(text)}</pre><p>{verdicts}</p>'
            f'<p class="dim">{_esc(payload["why_this_label"])}</p></dd>'
        )
    return (
        '<div class="panel"><h4>The minimal pair</h4>'
        "<p>Two payloads with the same labels, the same length and the same bytes but one: "
        "where the first holds a space, the second holds a newline, shown here as "
        '<span class="mono">↵</span>. The trigger is isolated. The mechanism behind it '
        "is not, and nothing here claims otherwise.</p>"
        f'<dl class="deflist">{"".join(blocks)}</dl></div>'
    )


def _replay_rows(run: dict) -> str:
    triggers = [
        _row(
            (
                _esc(trigger["side"]),
                _esc(trigger["candle_index"]),
                _esc(trigger["open_time"]),
                f'<span class="mono">{_esc(trigger["price"])}</span>',
                f'<span class="mono">{_esc(trigger["close"])}</span>',
            ),
            header=_esc(trigger["level_index"]),
        )
        for trigger in run["replay"]["triggers"]
    ]
    fired = _table(
        f"Every level the replay fired over {run['replay']['n_candles']} candles: "
        f"{run['replay']['n_buy_triggers']} of {run['replay']['n_buy_levels']} buy levels and "
        f"{run['replay']['n_sell_triggers']} of {run['replay']['n_sell_levels']} sell levels. "
        "Prices are integer atomic units of quote per whole base.",
        ("Level", "Side", "Candle", "Open time (ms)", "Level price", "Candle close"),
        triggers,
    )
    arms = _table(
        "The three arms over the identical window. The replay bought nothing, so it has no "
        "average price and holds no base; the nulls are computed over the same series either "
        "way, because an arm that reports nothing is still an arm that ran.",
        ("Arm", "Trades", "Quote committed", "Average buy price", "Base acquired"),
        [
            _row(
                (
                    _esc(run["replay"]["n_buy_triggers"]),
                    _esc(run["replay"]["quote_committed"]),
                    _esc(run["replay"]["average_buy_price"] or "none — nothing was bought"),
                    _esc(run["replay"]["base_acquired"]),
                ),
                header="replay",
            ),
            _row(
                (
                    _esc(run["buy_and_hold"]["trades"]),
                    _esc(run["buy_and_hold"]["quote_committed"]),
                    _esc(run["buy_and_hold"]["average_buy_price"]),
                    _esc(run["buy_and_hold"]["base_acquired"]),
                ),
                header="buy_and_hold",
            ),
            _row(
                (
                    _esc(run["random_entry"]["trades"]),
                    _esc(run["random_entry"]["quote_committed"]),
                    _esc(
                        f"{run['random_entry']['n_drawn']} of "
                        f"{run['random_entry']['draws_planned']} planned draws taken"
                    ),
                    _esc(
                        "draws worse than the replay: "
                        + _rate(run["random_entry"]["draws_worse_than_the_replay"])
                    ),
                ),
                header="random_entry",
            ),
        ],
    )
    return fired + arms


def _runs(experiment: dict) -> str:
    """Every observation behind this experiment's figures, in the shape its data takes."""
    experiment_id = experiment["experiment_id"]
    if experiment_id == "01-liquidity-arithmetic":
        return _pool_rows(experiment["run"])
    if experiment_id == "03-security-corpus":
        return _minimal_pair(experiment) + _payload_rows(experiment)
    return _replay_rows(experiment["run"])


def _experiment(experiment: dict) -> str:
    spec = experiment["spec"]
    run = experiment["run"]
    experiment_id = experiment["experiment_id"]
    finding = run.get("finding", "")
    return (
        f'<section id="{_esc(experiment_id)}" aria-labelledby="{_esc(experiment_id)}-h">'
        f'<h2 id="{_esc(experiment_id)}-h">{_esc(experiment_id)}</h2>'
        f"<p>{_esc(spec['question'])}</p>"
        + _headline(experiment["headline"])
        + _registration(spec)
        + "<h3>The falsifier, evaluated</h3>"
        + _falsifier(experiment["falsifier_result"])
        + "<h3>Every run behind those figures</h3>"
        + _runs(experiment)
        + '<div class="panel"><h4>How it was measured</h4>'
        + f'<p class="dim">{_esc(run["method"])}</p>'
        + (f"<h4>What it found</h4><p>{_esc(finding)}</p>" if finding else "")
        + f'<p class="status-line"><span class="status-key">Run record cites</span>'
        f'<span class="mono">{_esc(run["spec_hash"])}</span></p></div>'
        "</section>"
    )


def render(report: dict) -> str:
    """The whole data half of the page, summary first and refutations named in it."""
    summary = report["summary"]
    return (
        '<section aria-labelledby="summary"><h2 id="summary">What the falsifiers did</h2>'
        f'<p class="lede">{_esc(summary["statement"])}</p>'
        + _table(
            "Every pre-registered claim, and what its own falsifier came to when it was "
            "evaluated against the measured figures.",
            ("Experiment", "Claim", "Result"),
            [
                _row(
                    (
                        _esc(experiment["spec"]["claim"]),
                        "refuted" if experiment["falsifier_result"]["refuted"] else "survived",
                    ),
                    header=f'<a href="#{_esc(experiment["experiment_id"])}">'
                    f"{_esc(experiment['experiment_id'])}</a>",
                )
                for experiment in report["experiments"]
            ],
        )
        + f'<p class="dim">{_esc(report["method"])}</p></section>'
        + "".join(_experiment(experiment) for experiment in report["experiments"])
    )


def fill(shell: str, report: dict) -> str:
    """Put the records into the authored page, or refuse to serve a page without them.

    A shell that had lost its marker would render as a report with no experiments in it and
    nothing about the response would say so, which is the one failure mode worth raising for.
    """
    if MARKER not in shell:
        raise ValueError(
            f"advantage v2: the page shell carries no {MARKER} — the records have nowhere to go, "
            "and a report served without its runs is the defect this page exists to answer"
        )
    return shell.replace(MARKER, render(report))
