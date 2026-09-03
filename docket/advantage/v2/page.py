"""The v2 report as HTML, rendered from the same payload the JSON route serves.

The page and the JSON cannot disagree, because there is only one of them. v1's page is
authored markup guarded by a drift test that re-derives every figure from the experiment
files — a test that catches drift after it has been written. Here the drift is unavailable:
`render` takes `report.report()` and nothing else, so a figure on the page is the figure in
the document by construction, and the authored half of the page holds no numbers at all.

What the page shows that an aggregate would not: every pool row behind the two liquidity
distributions, every security scan from both dated detector experiments, including the ones
that failed, and every trigger the replay fired. Failures are rendered in their place in the
denominator rather than filtered out, which is the whole reason they were retained.

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
    sensitivity = headline["margin"].get("sensitivity")
    sensitivity_text = (
        f'<p class="dim">{_esc(sensitivity["statement"])}</p>' if sensitivity else ""
    )
    interpretation = headline.get("null_interpretation")
    interpretation_html = (
        '<div class="panel"><h3>Null interpretation</h3>'
        f"<p>{_esc(interpretation['statement'])}</p></div>"
        if interpretation
        else ""
    )
    return (
        f'<p class="lede">{_esc(headline["statement"])}</p>'
        '<div class="panel"><h3>Margin over the null</h3>'
        f"<p>{_esc(headline['margin']['statement'])}</p>{sensitivity_text}</div>"
        '<div class="panel"><h3>The nulls, computed over the same data</h3>'
        f'<dl class="deflist">{nulls}</dl></div>{interpretation_html}'
    )


def _null_figure(figure: dict) -> str:
    if "rate" in figure:
        return _rate(figure["rate"])
    if "distribution" in figure:
        return _distribution(figure["distribution"])
    if "usd" in figure:
        return f"{figure['usd']:,.6f} US dollars"
    return str(figure.get("value"))


def _registration(spec: dict) -> str:
    """The hashed specification, including the sentence that would refute it."""
    return (
        '<div class="panel"><h3>The registered specification</h3>'
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


def _provenance(provenance: dict) -> str:
    producer = provenance["committed_run_producer"]
    producer_text = (
        f"Committed producer: {producer['path']}."
        if producer["present"]
        else "No executable producer for the committed run is present in the repository."
    )
    changes = "".join(
        f"<dt>Post-run re-registration</dt><dd>{_esc(change['statement'])}</dd>"
        for change in provenance["post_run_re_registrations"]
    )
    return (
        '<div class="panel"><h3>Registration provenance</h3><dl class="deflist">'
        f'<dt>State</dt><dd><span class="mono">{_esc(provenance["state"])}</span></dd>'
        f"<dt>What git establishes</dt><dd>{_esc(provenance['statement'])}</dd>"
        f"<dt>Run producer</dt><dd>{_esc(producer_text)}</dd>"
        f"{changes}"
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
    labels = {
        payload["payload_id"]: payload for payload in experiment["dataset"]["payloads"]
    }
    rows = []
    for entry in experiment["run"]["payloads"]:
        payload = labels[entry["arm_name"]]
        cells = [_esc(", ".join(payload["labels"]) or "benign control")]
        cells += [_pass_cell(trial) for trial in entry["trials"]]
        cells.append(_esc(sum(trial["attempts"] for trial in entry["trials"])))
        rows.append(
            _row(cells, header=f'<span class="mono">{_esc(entry["arm_name"])}</span>')
        )
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
    payloads = {
        payload["payload_id"]: payload for payload in experiment["dataset"]["payloads"]
    }
    scored = {entry["arm_name"]: entry for entry in experiment["run"]["payloads"]}
    blocks = []
    for payload_id in MINIMAL_PAIR:
        payload = payloads[payload_id]
        text = payload["text"].replace("\n", "↵\n")
        verdicts = " / ".join(
            _pass_cell(trial) for trial in scored[payload_id]["trials"]
        )
        blocks.append(
            f'<dt><span class="mono">{_esc(payload_id)}</span></dt>'
            f'<dd><pre class="mono">{_esc(text)}</pre><p>{verdicts}</p>'
            f'<p class="dim">{_esc(payload["why_this_label"])}</p></dd>'
        )
    return (
        '<div class="panel"><h3>The minimal pair</h3>'
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
                    _esc(
                        run["replay"]["average_buy_price"]
                        or "none — nothing was bought"
                    ),
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


def _seal_rows(experiment: dict) -> str:
    """Every execution seal in the chain, confirmed or not, in the order it was written."""
    measurement = experiment["measurement"]
    execution = measurement["execution"]
    rows = [
        _row(
            (
                _esc(seal["ts"]),
                _esc(seal["kind"]),
                f"{_esc(seal['from_asset'])} &rarr; {_esc(seal['to_asset'])}",
                f"{seal['notional_usd']:,.2f}",
                _esc(seal["outcome"] or "no outcome recorded"),
                "confirmed" if seal["confirmed_execution"] else "not confirmed",
                f'<span class="mono">{_esc(seal["tx_hash"])}</span>'
                if seal["tx_hash"]
                else "none",
                f'<span class="mono">{_esc(seal["pre_trade_anchor_tx_hash"])}</span>'
                if seal["pre_trade_anchor_tx_hash"]
                else "none",
                _esc(seal["commitment_seq"]),
            ),
            header=_esc(seal["seq"]),
        )
        for seal in measurement["seals"]
    ]
    seals = _table(
        f"All {len(rows)} execution seals, of which "
        f"{execution['confirmed_over_seals']['numerator']} reach a confirmed execution. A seal "
        "the agent left unresolved is shown where it happened and keeps its place in the "
        "denominator; it is never re-read as either a success or a failure. A tx_hash is what "
        "the receipt asserts, not a block read here.",
        (
            "Seq",
            "Written at",
            "Kind",
            "Pair",
            "Notional (USD)",
            "Outcome",
            "Confirmed",
            "Transaction",
            "Pre-trade anchor",
            "Commitment seq",
        ),
        rows,
    )
    steps = _table(
        f"The {measurement['equity']['n_largest_steps_shown']} largest steps in the equity "
        f"series, over the {measurement['equity']['n_steps_considered']} steps considered. "
        f"{len(measurement['equity']['steps_no_recorded_trade_explains'])} exceed "
        f"{measurement['equity']['notional_bound_usd']:,.2f} US dollars, the largest notional "
        "any intent in the chain records, so no single trade here explains them. Some of them "
        "sit a few receipts from a step of the opposite sign and almost the same size, which "
        "is what a failed balance read looks like and is not what a deposit looks like — and "
        "the chain says which it was for none of them.",
        ("From seq", "To seq", "Written at", "From (USD)", "To (USD)", "Step (USD)"),
        [
            _row(
                (
                    _esc(step["to_seq"]),
                    _esc(step["ts"]),
                    f"{step['from_equity_usd']:,.2f}",
                    f"{step['to_equity_usd']:,.2f}",
                    f"{step['step_usd']:+,.2f}",
                ),
                header=_esc(step["from_seq"]),
            )
            for step in measurement["equity"]["largest_steps"]
        ],
    )
    return seals + steps


def _solvent_chain(experiment: dict) -> str:
    """The two integrity limbs, and the one check the chain cannot make for itself."""
    chain = experiment["measurement"]["chain"]
    cross = chain["anchor_cross_check"]
    return (
        '<div class="panel"><h3>The chain, recomputed</h3><dl class="deflist">'
        f"<dt>Published hashes recomputed</dt><dd>{_rate(chain['content_hashes_recomputed'])}"
        f' under <span class="mono">{_esc(chain["recipe"])}</span></dd>'
        f"<dt>prev_hash links</dt><dd>{_rate(chain['linkage_recomputed'])}, genesis prev_hash "
        f"{_esc(chain['genesis_prev_hash'])}</dd>"
        "<dt>Where the recipe was decided</dt><dd>"
        f"{_rate(chain['ascii_insensitive_recipe_agrees'])} of the receipts hash the same way "
        "under this repository's own receipt digest, which differs in one argument. The "
        f"{_esc(chain['receipts_the_two_recipes_disagree_on'])} that carry a non-ASCII "
        "character are the only place the two can disagree, and they are where a verifier "
        "that guessed wrong would report a chain that verifies almost everywhere.</dd>"
        f'<dt>Head</dt><dd><span class="mono">{_esc(chain["head_hash"])}</span> at seq '
        f"{_esc(chain['head_seq'])}</dd>"
        f"<dt>Against an on-chain anchor</dt><dd>{_esc(cross['statement'])}</dd>"
        "</dl></div>"
    )


def _solvent_no_return(experiment: dict) -> str:
    """Why no return figure is served, with the readings that decided it."""
    no_return = experiment["no_return"]
    funding = no_return["funding_fields"]
    readings = "".join(
        f'<dt><span class="mono">{_esc(path)}</span></dt><dd>{_esc(reading)}</dd>'
        for path, reading in funding["readings"].items()
    )
    failures = "".join(
        f"<dt>seq {_esc(failure['seq'])}</dt><dd>{_esc(failure['ts'])} reads "
        f"{failure['equity_usd']:,.2f} between two readings of "
        f"{failure['previous_equity_usd']:,.2f}. It is a failed read of the balance rather "
        "than an account that emptied and refilled, and it is excluded from the step series "
        "with the exclusion stated here.</dd>"
        for failure in no_return["read_failures"]
    )
    return (
        '<div class="panel"><h3>No return figure is served, and this is why</h3>'
        f"<p>{_esc(no_return['statement'])}</p>"
        f'<dl class="deflist">{failures}'
        "<dt>Fields that would record funding</dt><dd>"
        f"{len(funding['candidates'])} of the "
        f"{len(experiment['measurement']['equity']['key_paths'])} key paths in the chain carry "
        f"one of the {len(funding['words_searched'])} searched words, and "
        f"{len(funding['fields_recording_money_into_or_out_of_the_account'])} record money "
        "moving into or out of the account. Each candidate is read out below; the whole key "
        "path list is served in the JSON so a reader can apply a different definition to "
        "it.</dd>"
        f"{readings}</dl></div>"
    )


def _deposit_rows(experiment: dict) -> str:
    """Every reading the deposit-adjusted result was subtracted from, and the two deposits."""
    measurement = experiment["measurement"]
    balances = _table(
        "Every balance the account was read at, as an archive node answered at that block. "
        "The two window blocks are the seconds the receipt chain's own first and last receipt "
        "record; the other four are each deposit's block and the block before it, which is the "
        "pair a balance delta has to be read across. ETH is read at each of them and valued at "
        "none of them: it is zero at the opening and dust at the close, which is why the dollar "
        "result needs no price.",
        (
            "Block",
            "Reading",
            "USDT",
            "USDC",
            "ETH",
            "Dollar-pegged (USD)",
            "Transactions sent by then",
        ),
        [
            _row(
                (
                    _esc(reading["label"].replace("_", " ")),
                    f"{reading['usdt']:,.6f}",
                    f"{reading['usdc']:,.6f}",
                    f"{reading['eth']:.10g}",
                    f"{reading['stables_usd']:,.6f}",
                    _esc(reading["transaction_count"]),
                ),
                header=_esc(reading["block_number"]),
            )
            for reading in measurement["evidence"]["balance_readings"]
        ],
    )
    checks = _table(
        "Both external deposits, and every property rechecked on each of them from the frozen "
        "transaction and its receipt. An external deposit is a transfer of value into the "
        "wallet that some other address sent, so no leg of a trade the account made can be one "
        "however much it moved.",
        (
            "Deposit",
            "Block",
            "Sender",
            "Amount (USD)",
            "Balance delta (USD)",
            "Properties held",
        ),
        [
            _row(
                (
                    _esc(deposit["block_number"]),
                    f'<span class="mono">{_esc(deposit["sender"])}</span>',
                    f"{deposit['amount_usd']:,.6f}",
                    f"{deposit['balance_delta_usd']:,.6f}",
                    f"{sum(deposit['checks'].values())} of {len(deposit['checks'])}",
                ),
                header=f'<span class="mono">{_esc(deposit["tx_hash"])}</span>',
            )
            for deposit in measurement["flows"]["deposits"]
        ],
    )
    grid = measurement["time_weighted"]
    marks = _table(
        "The time-weighted return at each registered ETH mark, published as a table because "
        "the second deposit lands while most of the account's value sits in a token this "
        f"record did not price. Over the marks it runs from {grid['spread']['lowest'] * 100:.2f}"
        f"% to {grid['spread']['highest'] * 100:.2f}%, which is wider than the figure would be "
        "and does not settle the sign. No row is the answer.",
        ("ETH mark (USD)", "Sub-period returns", "Time-weighted return"),
        [
            _row(
                (
                    ", ".join(
                        f"{period['sub_period_return'] * 100:+.2f}%"
                        for period in row["sub_periods"]
                    ),
                    f"{row['time_weighted_return'] * 100:+.2f}%",
                ),
                header=f"{row['eth_mark_usd']:,}",
            )
            for row in grid["rows"]
        ],
    )
    return balances + checks + marks


def _deposit_disclosures(experiment: dict) -> str:
    """The three sentences the headline is dishonest without, beside the headline itself."""
    adjusted = experiment["deposit_adjusted"]
    return (
        '<div class="panel"><h3>What this figure is not</h3>'
        f"<dl class=\"deflist\"><dt>It is the wallet's return, not provably the agent's</dt>"
        f"<dd>{_esc(adjusted['attribution'])}</dd>"
        f"<dt>Gas is excluded, so the loss is a floor</dt><dd>{_esc(adjusted['gas'])}</dd>"
        "<dt>The deposit set is owner-attested, not swept here</dt>"
        f"<dd>{_esc(adjusted['completeness'])}</dd>"
        "<dt>No time-weighted return is published as a figure</dt>"
        f"<dd>{_esc(adjusted['time_weighted'])}</dd>"
        "<dt>It adds to 06 and refutes nothing in it</dt>"
        f"<dd>{_esc(adjusted['cross_reference']['statement'])}</dd>"
        "</dl></div>"
    )


def _runs(experiment: dict) -> str:
    """Every observation behind this experiment's figures, in the shape its data takes."""
    experiment_id = experiment["experiment_id"]
    if experiment_id == "01-liquidity-arithmetic":
        return _pool_rows(experiment["run"])
    if experiment_id in ("03-security-corpus", "05-security-corpus-postfix"):
        return _minimal_pair(experiment) + _payload_rows(experiment)
    if experiment_id == "06-solvent-record":
        return _seal_rows(experiment)
    if experiment_id == "07-solvent-deposit-adjusted":
        return _deposit_rows(experiment)
    return _replay_rows(experiment["run"])


def _experiment(experiment: dict) -> str:
    spec = experiment["spec"]
    run = experiment["run"]
    experiment_id = experiment["experiment_id"]
    finding = run.get("finding", "")
    run_status = experiment.get("run_status")
    run_status_html = (
        '<div class="panel"><h3>Run status</h3>'
        f"<p>{_esc(run_status['statement'])}</p></div>"
        if run_status
        else ""
    )
    detector = experiment.get("detector")
    detector_html = (
        '<div class="panel"><h3>Detector measured</h3>'
        f"<p>{_esc(detector['statement'])}</p>"
        f'<p class="status-line"><span class="status-key">Run SHA-256</span>'
        f'<span class="mono">{_esc(detector["run_sha256"])}</span></p></div>'
        if detector
        else ""
    )
    ship_gate = experiment.get("v3_04_ship_gate")
    ship_gate_html = (
        '<div class="panel"><h3>v3-04 ship gate</h3>'
        f"<p>{_esc(ship_gate['statement'])}</p></div>"
        if ship_gate
        else ""
    )
    chain_html = (
        _solvent_chain(experiment) if experiment_id == "06-solvent-record" else ""
    )
    no_return_html = (
        _solvent_no_return(experiment) if experiment.get("no_return") else ""
    )
    disclosures_html = (
        _deposit_disclosures(experiment)
        if experiment_id == "07-solvent-deposit-adjusted"
        else ""
    )
    return (
        f'<section id="{_esc(experiment_id)}" aria-labelledby="{_esc(experiment_id)}-h">'
        f'<h2 id="{_esc(experiment_id)}-h">{_esc(experiment_id)}</h2>'
        f"<p>{_esc(spec['question'])}</p>"
        + run_status_html
        + detector_html
        + ship_gate_html
        + chain_html
        + no_return_html
        + _headline(experiment["headline"])
        + disclosures_html
        + "<h3>The falsifier, evaluated</h3>"
        + _falsifier(experiment["falsifier_result"])
        + '<div class="evidence-record">'
        + _provenance(experiment["registration_provenance"])
        + _registration(spec)
        + "<h3>Every run behind those figures</h3>"
        + _runs(experiment)
        + '<div class="panel"><h3>How it was measured</h3>'
        + f'<p class="dim">{_esc(run["method"])}</p>'
        + (
            f'<p class="status-key">What it found</p><p>{_esc(finding)}</p>'
            if finding
            else ""
        )
        + f'<p class="status-line"><span class="status-key">Run record cites</span>'
        f'<span class="mono">{_esc(run["spec_hash"])}</span></p></div>'
        "</div>"
        "</section>"
    )


def render(report: dict, experiment_id: str | None = None) -> str:
    """The whole data half of the page, summary first and refutations named in it."""
    summary = report["summary"]
    summary_sentence = summary["statement"].split(". The refutation", 1)[0] + "."
    return (
        '<section aria-labelledby="summary"><h2 id="summary">What the falsifiers did</h2>'
        f'<p class="lede">{_esc(summary_sentence)}</p>'
        + _table(
            "Every registered claim, and what its own falsifier came to when it was "
            "evaluated against the measured figures.",
            ("Experiment", "Claim", "Result"),
            [
                _row(
                    (
                        _esc(experiment["spec"]["claim"]),
                        "refuted"
                        if experiment["falsifier_result"]["refuted"]
                        else "survived",
                    ),
                    header=(
                        f'<a id="{_esc(experiment["experiment_id"])}" '
                        f'href="/advantage/v2/{_esc(experiment["experiment_id"])}">'
                        f"{_esc(experiment['experiment_id'])}</a>"
                    ),
                )
                for experiment in report["experiments"]
            ],
        )
        + f'<p class="dim">{_esc(report["method"])}</p></section>'
        + "".join(
            _experiment(experiment)
            for experiment in report["experiments"]
            if experiment_id == experiment["experiment_id"]
        )
    )


def fill(shell: str, report: dict, experiment_id: str | None = None) -> str:
    """Put the records into the authored page, or refuse to serve a page without them.

    A shell that had lost its marker would render as a report with no experiments in it and
    nothing about the response would say so, which is the one failure mode worth raising for.
    """
    if MARKER not in shell:
        raise ValueError(
            f"advantage v2: the page shell carries no {MARKER} — the records have nowhere to go, "
            "and a report served without its runs is the defect this page exists to answer"
        )
    if experiment_id is not None and experiment_id not in {
        experiment["experiment_id"] for experiment in report["experiments"]
    }:
        raise KeyError(experiment_id)
    return shell.replace(MARKER, render(report, experiment_id))
