"""What v2 serves: the registrations, every run behind them, and the falsifiers evaluated.

v1 is three tasks, one run each, and it says so in its own method string. This is the other
report — registered, repeated where repetition was possible, and published whichever way
it came out. It does not replace v1 and nothing here overwrites it: v1 keeps its route, its
JSON and its page byte for byte, and is linked from this one as the prior version.

Three things are computed here rather than read, because each is a place a published report
can quietly stop being checkable.

**The falsifier's result.** Every spec registered the result that would refute its claim, and
until now nothing evaluated whether any of them fired. Each is evaluated clause by clause
against the measured figures, in one shape across all three experiments, and one of the three
claims is refuted — the grid replay's, which never bought at a single level. That result is on
the record it belongs to and it is also in the summary above the experiments, because a reader
who has to go looking for a refutation is a reader who will quote the two that held.

**The headline's margin.** A rate served without the distance between it and its null is a
figure a reader cannot weigh. The hired scanner flags 14 of 31 labelled attacks where a
sixteen-word keyword list flags 12 of the same 31: the margin is two payloads, and it is
served as two payloads rather than left to a reader to subtract.

**The security scores themselves.** They are recomputed from the committed corpus and the
committed run every time this is served, by the same `scoring` functions the tests use, so a
figure on the page, a figure in this JSON and a figure on a service card cannot be three
transcriptions that drift. The three nulls are computed the same way and travel beside every
agent figure.

One thing a reader should know before quoting 03: its claim was re-registered after the run.
The sentence originally registered could not fail — it compared class-level naming against a
null that emits no classes at all — so it was rewritten in the words of the falsifier that
actually decides it. That falsifier is unchanged and was registered before the run; the git
history holds the sentence it replaced; and no observation moved. `registered_at` on that spec
postdates its run for exactly that reason, and this paragraph is why.
"""

import json
from pathlib import Path

from . import scoring
from .spec import load

V2_DIR = Path(__file__).parent
SPECS_DIR = V2_DIR / "specs"
RUNS_DIR = V2_DIR / "runs"
CORPUS_PATH = V2_DIR / "corpus" / "security" / "payloads.json"

# In the order a reader meets them. 02 has no v2 experiment: v1's trading task measured a
# relay of somebody else's dated read, and there is nothing in this build to run repeatedly
# against it. An absent experiment is said here rather than implied by a gap in the numbering.
EXPERIMENT_IDS = ("01-liquidity-arithmetic", "03-security-corpus", "04-grid-replay")

# Git facts verified from the commits that introduced each spec and completed run. The state is
# derived below rather than separately transcribed: only a distinct earlier spec commit supports
# a git-provable ordering. 01 and 03 have no committed executable producer; their calculation and
# scoring modules do not write the committed run records.
REGISTRATION_HISTORY = {
    "01-liquidity-arithmetic": {
        "spec_commit": "b9578b8",
        "run_commit": "b9578b8",
        "spec_precedes_run": False,
        "committed_run_producer": {"present": False, "path": None},
    },
    "03-security-corpus": {
        "spec_commit": "9042e72",
        "run_commit": "9042e72",
        "spec_precedes_run": False,
        "committed_run_producer": {"present": False, "path": None},
    },
    "04-grid-replay": {
        "spec_commit": "b47c307",
        "run_commit": "9168194",
        "spec_precedes_run": True,
        "committed_run_producer": {
            "present": True,
            "path": "docket/advantage/v2/replay.py",
        },
    },
}

POST_RUN_RE_REGISTRATIONS = {
    "03-security-corpus": [
        {
            "field": "claim",
            "commit": "adb352b",
            "timing": "after_run",
            "falsifier_changed": False,
            "spec_hash_citations_changed": 48,
            "observations_changed": False,
            "statement": (
                "The claim was rewritten after the run at adb352b. Its falsifier is "
                "byte-identical to the one that predates the run. The run-record diff "
                "repoints 48 spec_hash citations and changes no observation."
            ),
        },
        {
            "field": "question",
            "commit": "the commit containing this record",
            "timing": "after_run",
            "falsifier_changed": False,
            "spec_hash_citations_changed": 48,
            "observations_changed": False,
            "statement": (
                "The question was rewritten after the run because keyword_match emits no "
                "classes, so asking whether the hired scanner named classes more often "
                "compared unlike outputs. It now asks the decision-level comparison in the "
                "claim and unchanged falsifier. The run-record diff repoints 48 spec_hash "
                "citations and changes no observation."
            ),
        },
    ]
}

PRIOR_VERSION = {
    "json": "/advantage.json",
    "page": "/advantage",
    "note": (
        "v1 is three tasks, each run once by hiring an agent and once by hand, and it is "
        "unchanged and still served. It is the only place in this build where an agent arm is "
        "compared against a human one, and that comparison is n=1 by construction. v2 does not "
        "supersede it: repeated trials here are agent-versus-null-baseline, and no human arm "
        "was simulated to stand in for the one v1 performed."
    ),
}

METHOD = (
    "Each experiment has a hashed specification naming its metric, null baselines, planned "
    "runs, stopping rule and falsifier, and every run record cites that hash. Registration "
    "provenance is stated per experiment: git establishes that 04's specification predates its "
    "run, while 01 and 03 are self-attested because each specification and completed run entered "
    "history together. Every trial is published, including the ones that failed — a failed "
    "trial keeps its place in the denominator and is never re-run until it passes — and every "
    "rate carries the two counts it was computed from. Where a rate has no observations behind "
    "it, its value is null rather than zero. In 03, the hired scanner and every null are scored "
    "over the same payload subset with a successful scan, and any missing payload marks the run "
    "incomplete rather than shrinking the experiment. Null baselines are computed rather than "
    "asserted, and they are served beside the agent figure they qualify rather than in a section "
    "a reader has to find. The falsifier of each experiment is evaluated against the measured "
    "figures and its result is served: one of the three claims is refuted, and which one is "
    "stated in the summary below before any experiment is described. Nothing here is a "
    "comparison against a human: v1 holds the only human arm in this build and it is n=1."
)


def registration_provenance(experiment_id: str) -> dict:
    """What repository history can establish about one registration's ordering."""
    history = REGISTRATION_HISTORY[experiment_id]
    post_run_re_registrations = POST_RUN_RE_REGISTRATIONS.get(experiment_id, [])
    git_provable = (
        history["spec_precedes_run"] and history["spec_commit"] != history["run_commit"]
    )
    if git_provable:
        statement = (
            f"Git establishes that the specification existed at {history['spec_commit']} in an "
            f"ancestor that did not contain the run, which entered history later at "
            f"{history['run_commit']}."
        )
    else:
        statement = (
            f"The specification and completed run first entered git together at "
            f"{history['spec_commit']}; their ordering rests on embedded timestamps written by "
            "the same author in the same session, not on independent git history."
        )
        if post_run_re_registrations:
            statement += (
                " The current registered_at postdates the run because the post-run "
                "re-registrations listed below replaced the claim and question after the "
                "observations were recorded."
            )
    return {
        "state": "git_provable" if git_provable else "self_attested",
        "statement": statement,
        "post_run_re_registrations": post_run_re_registrations,
        **history,
    }


def run(experiment_id: str) -> dict:
    """One committed run record, read from the repository and not from anywhere else."""
    return json.loads((RUNS_DIR / f"{experiment_id}.json").read_text(encoding="utf-8"))


def corpus() -> dict:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def security_scores() -> dict:
    """The hired scanner and its three nulls, scored over the committed corpus and run.

    Recomputed on every call rather than read out of the record. It is the one figure this
    report, the page and a service card all quote, and three transcriptions of a number are
    three chances for one of them to be stale.
    """
    payloads = corpus()
    record = run("03-security-corpus")
    observed = scoring.scan_results(record)
    scored_ids = set(observed["results"])
    scored_payloads = payloads | {
        "payloads": [
            payload
            for payload in payloads["payloads"]
            if payload["payload_id"] in scored_ids
        ]
    }
    return {
        "warden": scoring.score(
            payloads,
            observed["results"],
            failed_scans=observed["failed_scans"],
            unstable=observed["unstable"],
        ),
        "flag_nothing": scoring.score(
            scored_payloads, scoring.flag_nothing(scored_payloads)
        ),
        "flag_everything": scoring.score(
            scored_payloads, scoring.flag_everything(scored_payloads)
        ),
        "keyword_match": scoring.score(
            scored_payloads, scoring.keyword_match(scored_payloads)
        ),
    }


def _check(clause: str, refuted: bool, observed: str) -> dict:
    """One falsifier clause in the shape 04's record already writes it in."""
    return {"clause": clause, "refuted": refuted, "observed": observed}


def _result(checks: list[dict]) -> dict:
    return {"checks": checks, "refuted": any(check["refuted"] for check in checks)}


def _liquidity(record: dict) -> dict:
    """01's falsifier and headline, computed from the run's own distributions."""
    rounding = record["rounding_gap_pp"]
    gross = record["gross_gap_pp"]
    dominates = record["pools_where_gross_gap_exceeds_rounding_gap"]
    ratio = gross["median"] / rounding["median"] if rounding["median"] else None
    checks = [
        _check(
            "rounding_gap_zero_on_every_pool",
            rounding["max"] == 0,
            f"The largest absolute rounding gap over {rounding['n']} eligible pools is "
            f"{rounding['max']:.6g} percentage points, and the median is "
            f"{rounding['median']:.6g}.",
        ),
        _check(
            "gross_gap_not_larger_on_a_majority_of_pools",
            not (dominates["value"] is not None and dominates["value"] > 0.5),
            f"The absolute gross gap exceeds the absolute rounding gap on "
            f"{dominates['numerator']} of {dominates['denominator']} eligible pools.",
        ),
    ]
    return {
        "headline": {
            "statement": (
                f"Over {gross['n']} eligible pools in one registered snapshot, quoting the "
                f"gross fee rate moves the published rate by a median of {gross['median']:.6g} "
                f"percentage points where reading displayed figures rather than raw ones moves "
                f"it by a median of {rounding['median']:.6g}. The gross gap is the larger of "
                f"the two on {dominates['numerator']} of {dominates['denominator']} pools. The "
                "effect v1's narrative led with is the smaller one."
            ),
            "figure": {"name": "gross_gap_pp_median", "distribution": gross},
            "nulls": [
                {
                    "name": "quote_ui_rounded",
                    "figure": {
                        "name": "rounding_gap_pp_median",
                        "distribution": rounding,
                    },
                },
                {
                    "name": "quote_gross",
                    "figure": {"name": "gross_gap_pp_median", "distribution": gross},
                },
            ],
            "margin": {
                "value": ratio,
                "unit": "times the median rounding gap",
                "statement": (
                    f"The median gross gap is {ratio:.6g} times the median rounding gap "
                    f"({gross['median']:.6g} against {rounding['median']:.6g} percentage "
                    f"points, over {gross['n']} pools each)."
                    if ratio is not None
                    else "No median rounding gap to divide by."
                ),
            },
        },
        "falsifier_result": _result(checks),
    }


def _security(record: dict) -> dict:
    """03's falsifier and headline, computed from the corpus and the run rather than read."""
    scores = security_scores()
    warden = scores["warden"]["decision_level"]
    keyword = scores["keyword_match"]["decision_level"]
    everything = scores["flag_everything"]["decision_level"]
    counts = scores["warden"]["counts"]
    checks = [
        _check(
            "decision_recall_does_not_exceed_keyword_match",
            warden["recall"]["value"] <= keyword["recall"]["value"],
            f"The hired scanner did not leave {warden['recall']['numerator']} of "
            f"{warden['recall']['denominator']} labelled attacks at ALLOW, against "
            f"{keyword['recall']['numerator']} of the same "
            f"{keyword['recall']['denominator']} for the keyword list.",
        ),
        _check(
            "decision_precision_does_not_exceed_flag_everything",
            warden["precision"]["value"] <= everything["precision"]["value"],
            f"{warden['precision']['numerator']} of the "
            f"{warden['precision']['denominator']} payloads it flagged are labelled attacks, "
            f"against {everything['precision']['numerator']} of "
            f"{everything['precision']['denominator']} for an arm that flags everything, which "
            "is the corpus base rate.",
        ),
    ]
    margin = warden["recall"]["numerator"] - keyword["recall"]["numerator"]
    sensitivity_corpus = corpus()
    for payload in sensitivity_corpus["payloads"]:
        if payload["payload_id"] == "benign-meeting-note":
            payload["labels"] = ["ROLE_OVERRIDE"]
    observed = scoring.scan_results(record)
    sensitivity_scored = sensitivity_corpus | {
        "payloads": [
            payload
            for payload in sensitivity_corpus["payloads"]
            if payload["payload_id"] in observed["results"]
        ]
    }
    sensitivity_warden = scoring.score(sensitivity_scored, observed["results"])[
        "decision_level"
    ]["recall"]
    sensitivity_keyword = scoring.score(
        sensitivity_scored, scoring.keyword_match(sensitivity_scored)
    )["decision_level"]["recall"]
    unscored = counts["n_payloads_unscored"]
    run_status = {
        "state": "incomplete" if unscored else "complete",
        "n_payloads_unscored": unscored,
        "payloads_unscored": counts["payloads_unscored"],
        "statement": (
            f"Incomplete run: {unscored} of {counts['n_payloads']} corpus payloads had no "
            f"successful scan. Rates and nulls use the same {counts['n_scored']}-payload "
            "scored subset; this is not a smaller complete experiment."
            if unscored
            else f"Complete run: all {counts['n_payloads']} corpus payloads had at least one "
            "successful scan, so the hired scanner and every null are scored over the same "
            "full corpus."
        ),
    }
    return {
        # The labelled corpus travels with the run it was scored against. A detection rate whose
        # ground truth is only a digest is a rate a reader has to take on trust: the labels, the
        # reason for each and the text they were written about are all here.
        "dataset": corpus(),
        "scores": scores,
        "run_status": run_status,
        "headline": {
            "statement": (
                f"Over a labelled corpus of {counts['n_payloads']} payloads — "
                f"{counts['n_attacks_scored']} attacks and {counts['n_benign_scored']} benign "
                f"controls, three passes each — the hired scanner flagged "
                f"{warden['recall']['numerator']} of {warden['recall']['denominator']} labelled "
                f"attacks and named the labelled class on "
                f"{scores['warden']['class_level']['overall_recall']['numerator']} of them. "
                f"{counts['n_failed_scans']} of the "
                f"{counts['n_payloads'] * 3} scans failed and are counted as failed trials "
                "rather than as detection misses."
            ),
            "figure": {"name": "decision_level_recall", "rate": warden["recall"]},
            "nulls": [
                {
                    "name": name,
                    "figure": {
                        "name": "decision_level_recall",
                        "rate": scores[name]["decision_level"]["recall"],
                    },
                    "precision": scores[name]["decision_level"]["precision"],
                }
                for name in ("flag_nothing", "flag_everything", "keyword_match")
            ],
            "margin": {
                "value": margin,
                "unit": "payloads of the same 31",
                "statement": (
                    f"{margin} payloads. The hired scanner flagged "
                    f"{warden['recall']['numerator']} of "
                    f"{warden['recall']['denominator']} labelled attacks where the "
                    f"{len(scoring.KEYWORDS)}-word keyword list flagged "
                    f"{keyword['recall']['numerator']} of the same "
                    f"{keyword['recall']['denominator']}. Its decision-level precision is "
                    f"{warden['precision']['numerator']} of "
                    f"{warden['precision']['denominator']} against a corpus base rate of "
                    f"{everything['precision']['numerator']} of "
                    f"{everything['precision']['denominator']}."
                ),
                "sensitivity": {
                    "payload_id": "benign-meeting-note",
                    "reclassification": "benign control to ROLE_OVERRIDE attack",
                    "warden_recall": sensitivity_warden,
                    "keyword_match_recall": sensitivity_keyword,
                    "margin_payloads": (
                        sensitivity_warden["numerator"]
                        - sensitivity_keyword["numerator"]
                    ),
                    "corpus_edited": False,
                    "statement": (
                        "The benign-meeting-note label is contestable. Reclassifying it as a "
                        "ROLE_OVERRIDE attack gives the hired scanner 14 of 32 and "
                        "keyword_match 13 of 32, so the claim survives by one payload rather "
                        "than two. The corpus is left unedited because its bytes are hashed "
                        "into the registration."
                    ),
                },
            },
        },
        "falsifier_result": _result(checks),
    }


def _replay(record: dict) -> dict:
    """04's headline. Its falsifier result is the record's own — computed when it was run,
    and re-derived from the committed series by the tests rather than by a second recipe here."""
    fired = record["replay"]
    hold = record["buy_and_hold"]
    drawn = record["random_entry"]
    return {
        "headline": {
            "statement": (
                f"{record['notice']} The prices are Binance BNBUSDT while the plan addresses "
                "PancakeSwap WBNB/USDT; replaying one venue against the other assumes they "
                "track and is not evidence about the venue the plan trades. Over "
                f"{fired['n_candles']} candles of the registered window, "
                f"{fired['n_buy_triggers']} of the ladder's {fired['n_buy_levels']} buy levels "
                f"fired and {fired['n_sell_triggers']} of its {fired['n_sell_levels']} sell "
                "levels did, so there is no average buy price to place against either null and "
                "the comparison is empty. The claim registered for this experiment is refuted."
            ),
            "figure": {
                "name": "average_buy_price_over_a_replayed_ladder",
                "value": fired["average_buy_price"],
                "buy_triggers": scoring.rate(
                    fired["n_buy_triggers"], fired["n_buy_levels"]
                ),
            },
            "nulls": [
                {
                    "name": "buy_and_hold",
                    "figure": {
                        "name": "average_buy_price",
                        "value": hold["average_buy_price"],
                        "base_acquired": hold["base_acquired"],
                        "quote_committed": hold["quote_committed"],
                    },
                },
                {
                    "name": "random_entry",
                    "figure": {
                        "name": "average_buy_price",
                        "distribution": drawn["average_buy_price"],
                        "draws_planned": drawn["draws_planned"],
                        "draws_worse_than_the_replay": drawn[
                            "draws_worse_than_the_replay"
                        ],
                    },
                },
            ],
            "margin": {
                "value": None,
                "unit": "atomic units of quote per whole base",
                "statement": (
                    "There is no margin to report. The ladder bought at no level, so it has no "
                    "average price to be above or below either null's, and the share of seeded "
                    "draws that did worse is a rate over a denominator of zero."
                ),
            },
            "null_interpretation": {
                "state": "post_registration_reinterpretation",
                "registered_same_money_reading": {
                    "quote_committed": fired["quote_committed"],
                    "base_acquired": 0,
                    "average_buy_price": hold["average_buy_price"],
                },
                "published_capacity_reading": {
                    "quote_committed": hold["quote_committed"],
                    "base_acquired": hold["base_acquired"],
                    "average_buy_price": hold["average_buy_price"],
                },
                "falsifier_is_insensitive": True,
                "statement": (
                    "The registered same-money rule gives buy-and-hold zero quote because "
                    "the replay committed zero; at the first-close price that acquires zero "
                    "base. The published null gives it the five-level planned capacity: "
                    f"{hold['quote_committed']} quote, acquiring {hold['base_acquired']} base "
                    f"at {hold['average_buy_price']}. That is a post-registration "
                    "reinterpretation. The falsifier compares prices and also fires "
                    "independently because no buy level fired, so the choice of quote amount "
                    "does not affect the refutation."
                ),
            },
        },
        "falsifier_result": record["falsifier_result"],
    }


COMPUTED = {
    "01-liquidity-arithmetic": _liquidity,
    "03-security-corpus": _security,
    "04-grid-replay": _replay,
}


def experiments() -> list[dict]:
    """Every v2 experiment: its registration, its whole run, and what the two come to.

    The run travels in full — every pool row, every trial including the nine that failed,
    every trigger — because an aggregate served without the runs behind it is a number a
    reader cannot contest, and that is the defect this whole report exists to answer.
    """
    built = []
    for experiment_id in EXPERIMENT_IDS:
        spec = load(SPECS_DIR / f"{experiment_id}.json")
        record = run(experiment_id)
        built.append(
            {
                "experiment_id": experiment_id,
                "registration_provenance": registration_provenance(experiment_id),
                "spec": spec.as_record(),
                "run": record,
                **COMPUTED[experiment_id](record),
            }
        )
    return built


def report() -> dict:
    """The whole v2 payload, refutations first."""
    built = experiments()
    refuted = [
        experiment["experiment_id"]
        for experiment in built
        if experiment["falsifier_result"]["refuted"]
    ]
    return {
        "version": "v2",
        "page": "/advantage/v2",
        "prior_version": PRIOR_VERSION,
        "method": METHOD,
        "summary": {
            "n_experiments": len(built),
            "n_claims_refuted": len(refuted),
            "claims_refuted": refuted,
            "statement": (
                f"{len(refuted)} of {len(built)} registered claims was refuted by its own "
                f"falsifier: {', '.join(refuted)}. The refutation is published as it came out, "
                "and the experiment that produced it is served here in full beside the two that "
                "survived. Every claim's falsifier result is computed from the measured figures "
                "rather than restated."
                if refuted
                else f"None of the {len(built)} registered claims was refuted by its own "
                "falsifier."
            ),
        },
        "experiments": built,
    }
