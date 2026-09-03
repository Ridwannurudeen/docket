"""What v2 serves: the registrations, every run behind them, and the falsifiers evaluated.

v1 is three tasks, one run each, and it says so in its own method string. This is the other
report — registered, repeated where repetition was possible, and published whichever way
it came out. It does not replace v1 and nothing here overwrites it: v1 keeps its route, its
JSON and its page byte for byte, and is linked from this one as the prior version.

Three things are computed here rather than read, because each is a place a published report
can quietly stop being checkable.

**The falsifier's result.** Every spec registered the result that would refute its claim, and
until now nothing evaluated whether any of them fired. Each is evaluated clause by clause
against the measured figures, in one shape across all six experiments, and one of the six
claims is refuted — the grid replay's, which never bought at a single level. That result is on
the record it belongs to and it is also in the summary above the experiments, because a reader
who has to go looking for a refutation is a reader who will quote the ones that held.

**The headline's margin.** A rate served without the distance between it and its null is a
figure a reader cannot weigh. The detector observed 2026-08-10 flags 14 of 31 labelled
attacks where a sixteen-word keyword list flags 12 of the same 31, while the separately
registered 2026-08-24 detector run flags 15 of 30 scored attacks where the same null flags
12. Each margin is served rather than left to a reader to subtract.

**The security scores themselves.** They are recomputed from the committed corpus and each
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

import hashlib
import json
from pathlib import Path

from . import deposits, scoring, solvent
from .spec import load

V2_DIR = Path(__file__).parent
SPECS_DIR = V2_DIR / "specs"
RUNS_DIR = V2_DIR / "runs"
CORPUS_PATH = V2_DIR / "corpus" / "security" / "payloads.json"
SOLVENT_CORPUS_PATH = V2_DIR / "corpus" / "trading" / "solvent-receipts.json"
SOLVENT_FLOWS_PATH = V2_DIR / "corpus" / "trading" / "solvent-wallet-flows.json"
V1_TRADING_PATH = V2_DIR.parent / "experiments" / "02-trading.json"

# In the order a reader meets them. 02 has no v2 experiment of its own: v1's trading task
# timed a relay of somebody else's dated read, and a relay is not a thing to run repeatedly.
# 06 reads the same agent's chain and is a different question — not what the relay cost, but
# what the record behind it establishes — so it is a new registration and not a repeat of 02,
# and v1's task keeps its route, its figures and its own account of what it measured.
SECURITY_EXPERIMENT_IDS = (
    "03-security-corpus",
    "05-security-corpus-postfix",
)
EXPERIMENT_IDS = (
    "01-liquidity-arithmetic",
    *SECURITY_EXPERIMENT_IDS,
    "04-grid-replay",
    "06-solvent-record",
    "07-solvent-deposit-adjusted",
)
POSTFIX_REVISION = "0583853ed7fca7d03c98a5cc4c2383cc6b149248"
POSTFIX_DEPLOYED_AT = "2026-08-24"
V3_04_RECALL_FLOOR = 0.90
V3_04_PRECISION_FLOOR = 0.90

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
    "05-security-corpus-postfix": {
        "spec_commit": "b83bbb8",
        "run_commit": "eb5f9b0",
        "spec_precedes_run": True,
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
    # Both specs and both run records landed together in b2411b3, so spec and run share a commit
    # and neither ordering is git-provable: self_attested, like 01 and 03. The producers are
    # committed, so a reader can regenerate the run from the spec and the frozen corpus.
    "06-solvent-record": {
        "spec_commit": "b2411b3",
        "run_commit": "b2411b3",
        "spec_precedes_run": False,
        "committed_run_producer": {
            "present": True,
            "path": "docket/advantage/v2/solvent.py",
        },
    },
    "07-solvent-deposit-adjusted": {
        "spec_commit": "b2411b3",
        "run_commit": "b2411b3",
        "spec_precedes_run": False,
        "committed_run_producer": {
            "present": True,
            "path": "docket/advantage/v2/deposits.py",
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
    "provenance is stated per experiment: git establishes that 04 and 05's specifications "
    "predate their runs, while 01 and 03 are self-attested because each specification and "
    "completed run entered history together, and 06's and 07's specifications and runs are "
    "working-tree files that git records nothing about yet. Every trial is published, "
    "including the ones "
    "that failed — a failed "
    "trial keeps its place in the denominator and is never re-run until it passes — and every "
    "rate carries the two counts it was computed from. Where a rate has no observations behind "
    "it, its value is null rather than zero. In both security experiments, the hired scanner "
    "and every null are scored over the same payload subset with a successful scan, and any "
    "missing payload marks the run incomplete rather than shrinking the experiment. Null "
    "baselines are computed rather than asserted, and they are served beside the agent figure "
    "they qualify rather than in a section "
    "a reader has to find. The falsifier of each experiment is evaluated against the measured "
    "figures and its result is served: one of the six claims is refuted, and which one is "
    "stated in the summary below before any experiment is described. 07 reads the same agent's "
    "wallet on the chain it traded on and publishes an adverse result - a loss, once the "
    "money paid into the account is subtracted - and it neither refutes nor amends 06, whose "
    "claim and falsifier are about the fields inside 06's own corpus. Nothing here is a "
    "comparison against a human: v1 holds the only human arm in this build and it is n=1."
)


def registration_provenance(experiment_id: str) -> dict:
    """What repository history can establish about one registration's ordering."""
    history = REGISTRATION_HISTORY[experiment_id]
    post_run_re_registrations = POST_RUN_RE_REGISTRATIONS.get(experiment_id, [])
    git_provable = (
        history["spec_precedes_run"] and history["spec_commit"] != history["run_commit"]
    )
    if history["spec_commit"] is None:
        return {
            "state": "uncommitted",
            "statement": (
                "The specification and the run are working-tree files and neither is in git "
                "history, so history establishes nothing about their order and this record "
                "claims nothing from it. Their ordering rests on the embedded timestamps and "
                "on the account the specification's own stopping rule gives, which states "
                "that the corpus was frozen before the registration was written and that the "
                "headline counts were already recorded in a planning document before it. When "
                "the two are committed together this becomes a self-attested registration "
                "like 01 and 03, and not a git-provable one."
            ),
            "post_run_re_registrations": post_run_re_registrations,
            **history,
        }
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


def security_scores(experiment_id: str = "03-security-corpus") -> dict:
    """The hired scanner and its three nulls, scored over the committed corpus and run.

    Recomputed on every call rather than read out of the record. It is the one figure this
    report, the page and a service card all quote, and three transcriptions of a number are
    three chances for one of them to be stale.
    """
    payloads = corpus()
    record = run(experiment_id)
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


def _security_detector(record: dict) -> dict:
    experiment_id = record.get("spec_id", "03-security-corpus")
    run_sha256 = hashlib.sha256(
        (RUNS_DIR / f"{experiment_id}.json").read_bytes()
    ).hexdigest()
    if experiment_id == "03-security-corpus":
        return {
            "observed_at": record["started_at"][:10],
            "revision": None,
            "deployed_at": None,
            "revision_state": "unrecorded",
            "retained_unmodified": True,
            "run_sha256": run_sha256,
            "statement": (
                "This run measured the detector live on 2026-08-10. Its exact source "
                "revision and deploy date were not recorded; it predates the deployment of "
                f"{POSTFIX_REVISION} on {POSTFIX_DEPLOYED_AT}. The old run is retained "
                "byte-for-byte rather than rewritten after the detector changed."
            ),
        }
    revision = record["detector_revision"]
    deployed_at = record["detector_deployed_at"]
    return {
        "observed_at": record["started_at"][:10],
        "revision": revision,
        "deployed_at": deployed_at,
        "revision_state": "deployment_recorded_endpoint_not_self_attesting",
        "retained_unmodified": False,
        "run_sha256": run_sha256,
        "statement": (
            f"This separate run measured declared detector revision {revision}, deployed "
            f"{deployed_at}, on {record['started_at'][:10]}. The live health response did "
            "not expose a source commit, so the revision binding relies on the deployment "
            "record rather than endpoint self-attestation."
        ),
    }


def _security(record: dict) -> dict:
    """A security falsifier and headline, computed from the corpus and committed run."""
    experiment_id = record.get("spec_id", "03-security-corpus")
    scores = security_scores(experiment_id)
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
    full_corpus = corpus()
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
    sensitivity_margin = (
        sensitivity_warden["numerator"] - sensitivity_keyword["numerator"]
    )
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
    result = {
        # The labelled corpus travels with the run it was scored against. A detection rate whose
        # ground truth is only a digest is a rate a reader has to take on trust: the labels, the
        # reason for each and the text they were written about are all here.
        "dataset": corpus(),
        "scores": scores,
        "detector": _security_detector(record),
        "run_status": run_status,
        "headline": {
            "statement": (
                f"Over a labelled corpus of {counts['n_payloads']} payloads — "
                f"{sum(bool(payload['labels']) for payload in full_corpus['payloads'])} attacks "
                f"and {sum(not payload['labels'] for payload in full_corpus['payloads'])} benign "
                "controls, three passes each — first successful passes from the hired scanner "
                f"scored {counts['n_scored']} payloads and flagged "
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
                "unit": f"payloads of the same {warden['recall']['denominator']}",
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
                    "margin_payloads": sensitivity_margin,
                    "corpus_edited": False,
                    "statement": (
                        "The benign-meeting-note label is contestable. Reclassifying it as a "
                        "ROLE_OVERRIDE attack gives the hired scanner "
                        f"{sensitivity_warden['numerator']} of "
                        f"{sensitivity_warden['denominator']} and keyword_match "
                        f"{sensitivity_keyword['numerator']} of "
                        f"{sensitivity_keyword['denominator']}, so their margin is "
                        f"{sensitivity_margin} "
                        f"{'payload' if sensitivity_margin == 1 else 'payloads'}. The corpus "
                        "is left unedited because its bytes are hashed "
                        "into the registration."
                    ),
                },
            },
        },
        "falsifier_result": _result(checks),
    }
    if experiment_id == "05-security-corpus-postfix":
        recall_passes = warden["recall"]["value"] >= V3_04_RECALL_FLOOR
        precision_passes = warden["precision"]["value"] >= V3_04_PRECISION_FLOOR
        result["v3_04_ship_gate"] = {
            "recall_floor": V3_04_RECALL_FLOOR,
            "precision_floor": V3_04_PRECISION_FLOOR,
            "recall": warden["recall"],
            "precision": warden["precision"],
            "recall_passes": recall_passes,
            "precision_passes": precision_passes,
            "passes": False,
            "status": "beta",
            "statement": (
                "This separate v2 corpus rerun does not qualify v3-04: it is not the "
                "registered v3-04 held-out experiment, and its decision recall is "
                f"{warden['recall']['numerator']} of {warden['recall']['denominator']} "
                f"({warden['recall']['value'] * 100:.2f}%), below the 90% recall floor. "
                "Its decision precision is "
                f"{warden['precision']['numerator']} of {warden['precision']['denominator']} "
                f"({warden['precision']['value'] * 100:.2f}%), above the 90% precision floor. "
                "The conjunctive gate therefore remains unmet and Warden remains beta."
            ),
        }
    return result


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


def _solvent(record: dict) -> dict:
    """06's falsifier and headline, computed from the frozen chain rather than read.

    Read rather than recomputed, "the chain verifies" would be a sentence about a check
    somebody once ran, and the whole point of publishing a hash chain is that a reader does
    not have to take that on trust. So both integrity limbs, every count and both nulls are
    recomputed here from the same 384 receipts the registration hashed, on every call.
    """
    measured = solvent.measure(
        solvent.load_corpus(SOLVENT_CORPUS_PATH),
        json.loads(V1_TRADING_PATH.read_text(encoding="utf-8")),
    )
    chain = measured["chain"]
    execution = measured["execution"]
    equity = measured["equity"]
    loose = measured["nulls"]["count_every_seal_as_a_trade"]
    strict = measured["nulls"]["count_only_anchored_seals"]
    confirmed = execution["confirmed_over_seals"]
    commitments = execution["confirmed_over_commitments"]
    anchored = execution["seals_with_a_pre_trade_anchor"]
    funding = equity["funding_fields"][
        "fields_recording_money_into_or_out_of_the_account"
    ]
    checks = [
        _check(
            "hash_chain_does_not_verify",
            not chain["verifies"],
            f"{chain['content_hashes_recomputed']['numerator']} of "
            f"{chain['content_hashes_recomputed']['denominator']} published hashes are the "
            "digest of the body they are published beside, "
            f"{chain['linkage_recomputed']['numerator']} of "
            f"{chain['linkage_recomputed']['denominator']} prev_hash links hold, and the "
            f"genesis prev_hash is the zero word: {chain['genesis_prev_hash_is_the_zero_word']}"
            f". Receipts failing the content limb: {chain['content_failures']}. Receipts "
            f"failing the linkage limb: {chain['linkage_failures']}.",
        ),
        _check(
            "confirmed_executions_reach_half_the_commitments",
            commitments["value"] >= 0.5,
            f"{commitments['numerator']} of {commitments['denominator']} pre-trade "
            f"commitments reach a confirmed execution, which is "
            f"{commitments['value'] * 100:.2f}% of them.",
        ),
        _check(
            "anchored_seals_reach_a_tenth_of_the_seals",
            anchored["value"] >= 0.1,
            f"{anchored['numerator']} of {anchored['denominator']} execution seals carry a "
            f"pre_trade_anchor_tx_hash, which is {anchored['value'] * 100:.2f}% of them.",
        ),
        _check(
            "a_receipt_carries_a_funding_field",
            bool(funding),
            f"{len(equity['key_paths'])} distinct key paths appear across the 384 receipts. "
            f"{len(equity['funding_fields']['candidates'])} carry one of the "
            f"{len(equity['funding_fields']['words_searched'])} searched words and each is "
            f"read out on the record; {len(funding)} record money moving into or out of the "
            "account.",
        ),
    ]
    overstatement = loose["numerator"] - confirmed["numerator"]
    return {
        "measurement": measured,
        "headline": {
            "statement": (
                f"Over the {measured['phases']['n_receipts']} receipts of a closed "
                f"{measured['window']['first_receipt_ts'][:10]} to "
                f"{measured['window']['last_receipt_ts'][:10]} window, the chain verifies end "
                f"to end and {confirmed['numerator']} of {confirmed['denominator']} execution "
                "seals reach a confirmed execution — just over half of the seals, and "
                f"{commitments['numerator']} of the {commitments['denominator']} pre-trade "
                "commitments those seals answer, which is under half of those. "
                f"{execution['outcomes'].get('unresolved', 0)} seals were left unresolved and "
                "keep their place in the denominator; "
                f"{execution['seals_with_a_tx_hash_and_no_confirmation']['numerator']} name a "
                "transaction the chain never confirms; a pre-trade anchor appears on "
                f"{anchored['numerator']} of {anchored['denominator']} seals, so the record "
                "is not pre-committed on chain. No return, win rate or drawdown is "
                "computed from the "
                "equity series, and the reason is served with the figures rather than left as "
                "an omission."
            ),
            "figure": {"name": "confirmed_execution_share", "rate": confirmed},
            "nulls": [
                {
                    "name": "count_every_seal_as_a_trade",
                    "figure": {"name": "seals_counted_as_trades", "rate": loose},
                },
                {
                    "name": "count_only_anchored_seals",
                    "figure": {"name": "seals_with_a_pre_trade_anchor", "rate": strict},
                },
            ],
            "margin": {
                "value": overstatement,
                "unit": f"seals of the same {confirmed['denominator']}",
                "statement": (
                    f"{overstatement} seals. Counting every seal as a trade gives "
                    f"{loose['numerator']} of {loose['denominator']}, where "
                    f"{confirmed['numerator']} of the same {confirmed['denominator']} reach a "
                    f"confirmed execution — so the free reading overstates by {overstatement}. "
                    "In the other direction, counting only the seals whose commitment was "
                    "itself put on chain first gives "
                    f"{strict['numerator']} of {strict['denominator']}, so "
                    f"{confirmed['numerator'] - strict['numerator']} of the "
                    f"{confirmed['numerator']} confirmed executions rest on SOLVENT's own "
                    "word for when the intention behind them was written."
                ),
            },
        },
        "no_return": {
            "published": False,
            "first_equity_reading": equity["first"],
            "last_equity_reading": equity["last"],
            "read_failures": equity["read_failures"],
            "steps_no_recorded_trade_explains": equity[
                "steps_no_recorded_trade_explains"
            ],
            "notional_bound_usd": equity["notional_bound_usd"],
            "funding_fields": equity["funding_fields"],
            "statement": equity["no_return_published"],
        },
        "falsifier_result": _result(checks),
    }


def _deposit_adjusted(record: dict) -> dict:
    """07's falsifier and headline, recomputed from the two frozen corpora rather than read.

    Read rather than recomputed, "the account lost money" would be a sentence about a
    subtraction somebody once did. Every term of it is a hex string a public archive node
    returned, and all of them are here, so the subtraction is redone on every call and so is
    each of the twelve properties that make one of those transactions a deposit rather than a
    transfer the account made to itself.
    """
    measured = deposits.measure(
        deposits.load_corpus(SOLVENT_FLOWS_PATH),
        deposits.load_corpus(SOLVENT_CORPUS_PATH),
    )
    result = measured["result"]
    window = measured["window"]
    evidence = measured["evidence"]
    flows = measured["flows"]
    attributed = measured["attribution"]
    gas = measured["gas"]
    spread = measured["time_weighted"]["spread"]
    dietz = result["modified_dietz"]["return"]
    contributed = result["over_the_opening_balance_and_the_deposits"]
    balance_change = measured["nulls"]["count_the_balance_change_as_the_result"]
    doing_nothing = measured["nulls"]["hold_the_stables"]
    failing = [
        {
            "tx_hash": deposit["tx_hash"],
            "failed": sorted(
                name for name, held in deposit["checks"].items() if not held
            ),
        }
        for deposit in flows["deposits"]
        if not deposit["is_a_bare_external_deposit"]
    ]
    checks = [
        _check(
            "the_evidence_does_not_recompute",
            bool(failing)
            or not window["opening_block_is_the_first_receipts_own_second"]
            or not window["closing_block_is_the_last_receipts_own_second"]
            or not evidence["wallet_is_an_externally_owned_account"],
            f"Both deposits were rechecked against the frozen transaction and receipt on "
            f"{len(flows['deposits'][0]['checks'])} properties each and "
            f"{len(failing)} deposits failed any of them: {failing}. The opening block's "
            "timestamp is the first receipt's own second: "
            f"{window['opening_block_is_the_first_receipts_own_second']}; the closing block's "
            f"is the last receipt's: {window['closing_block_is_the_last_receipts_own_second']}. "
            "The wallet returns 0x from eth_getCode: "
            f"{evidence['wallet_is_an_externally_owned_account']}.",
        ),
        _check(
            "the_deposit_adjusted_result_is_not_a_loss",
            result["deposit_adjusted_pnl_usd"] >= 0,
            f"{result['closing_stables_usd']:,.6f} closing minus "
            f"{result['opening_stables_usd']:,.6f} opening minus "
            f"{result['external_deposits_usd']:,.6f} of external deposits is "
            f"{result['deposit_adjusted_pnl_usd']:,.6f} US dollars.",
        ),
        _check(
            "the_chain_names_every_transaction_the_wallet_sent",
            attributed["distinct_tx_hashes_the_chain_names"]
            >= attributed["transactions_the_wallet_sent"],
            f"The wallet sent {attributed['transactions_the_wallet_sent']} transactions over "
            f"the window and the chain names "
            f"{attributed['distinct_tx_hashes_the_chain_names']} distinct hashes, so at least "
            f"{attributed['wallet_transactions_the_chain_names_no_hash_for']['numerator']} of "
            f"{attributed['wallet_transactions_the_chain_names_no_hash_for']['denominator']} "
            "are named nowhere in it.",
        ),
        _check(
            "a_receipt_carries_the_native_coin_or_its_fee",
            gas["the_chain_could_have_carried_the_fees"],
            f"{len(gas['key_paths_matching'])} of the receipt chain's key paths carry one of "
            f"the {len(gas['words_searched'])} searched words: {gas['key_paths_matching']}. "
            f"The {gas['transactions_the_wallet_sent']} transactions the wallet sent were paid "
            "for outside the series, and this record holds "
            f"{gas['wallet_transaction_hashes_on_this_record']} of their hashes against the "
            f"{gas['wallet_transaction_hashes_the_chain_names']} the chain names.",
        ),
    ]
    return {
        "measurement": measured,
        "headline": {
            "statement": (
                f"Over the same closed window 06 covers, {flows['n_deposits']} external "
                f"deposits totalling {flows['external_deposits_usd']:,.6f} US dollars reached "
                f"SOLVENT's wallet and nothing was transferred out of it, so the account's "
                f"{result['balance_change_usd']:,.6f} balance change is a deposit-adjusted "
                f"LOSS of {abs(result['deposit_adjusted_pnl_usd']):,.6f} US dollars — "
                f"{dietz['value'] * 100:.2f}% of the capital it held weighted by how long it "
                f"held it, and {contributed['value'] * 100:.2f}% of the opening balance and "
                "the deposits together. That loss is the wallet's and is not provably the "
                f"agent's: the wallet sent {attributed['transactions_the_wallet_sent']} "
                f"transactions and the chain names "
                f"{attributed['distinct_tx_hashes_the_chain_names']} hashes, and chain data "
                "cannot separate a trade the agent's engine signed from one an operator "
                "signed with the same key. It also excludes the gas of every one of those "
                "transactions, so it is a floor. No time-weighted return is published as a "
                f"figure: over the registered marks it runs from {spread['lowest'] * 100:.2f}% "
                f"to {spread['highest'] * 100:.2f}% and does not settle the sign."
            ),
            "figure": {
                "name": "deposit_adjusted_pnl_usd",
                "usd": result["deposit_adjusted_pnl_usd"],
                "modified_dietz": dietz,
                "over_the_opening_balance_and_the_deposits": contributed,
            },
            "nulls": [
                {
                    "name": "count_the_balance_change_as_the_result",
                    "figure": {
                        "name": "balance_change_usd",
                        "usd": balance_change["result_usd"],
                    },
                },
                {
                    "name": "hold_the_stables",
                    "figure": {
                        "name": "deposit_adjusted_pnl_usd_of_doing_nothing",
                        "usd": doing_nothing["result_usd"],
                    },
                },
            ],
            "margin": {
                "value": result["deposit_adjusted_pnl_usd"]
                - doing_nothing["result_usd"],
                "unit": "US dollars against the same contributions",
                "statement": (
                    f"{result['deposit_adjusted_pnl_usd']:,.6f} US dollars. Doing nothing with "
                    f"the same opening balance and the same two contributions returns exactly "
                    f"{doing_nothing['result_usd']:,.2f} and sends "
                    f"{doing_nothing['transactions_sent']} transactions, so the whole of the "
                    "loss is the distance from leaving the money alone and the gas that arm "
                    "did not pay is on top of it. In the other direction, reading the balance "
                    f"change as the result gives {balance_change['result_usd']:,.6f} US "
                    f"dollars — the free reading, and wrong by the "
                    f"{flows['external_deposits_usd']:,.6f} that was paid in."
                ),
            },
        },
        "deposit_adjusted": {
            "published": True,
            "is_a_loss": result["is_a_loss"],
            "opening_stables_usd": result["opening_stables_usd"],
            "closing_stables_usd": result["closing_stables_usd"],
            "external_deposits_usd": result["external_deposits_usd"],
            "external_withdrawals_usd": flows["external_withdrawals_usd"],
            "deposit_adjusted_pnl_usd": result["deposit_adjusted_pnl_usd"],
            "modified_dietz": dietz,
            "over_the_opening_balance_and_the_deposits": contributed,
            "method": result["method"],
            "attribution": attributed["statement"],
            "gas": gas["statement"],
            "completeness": flows["completeness"],
            "time_weighted": measured["time_weighted"]["statement"],
            "cross_reference": record["cross_reference"],
        },
        "falsifier_result": _result(checks),
    }


COMPUTED = {
    "01-liquidity-arithmetic": _liquidity,
    "03-security-corpus": _security,
    "05-security-corpus-postfix": _security,
    "04-grid-replay": _replay,
    "06-solvent-record": _solvent,
    "07-solvent-deposit-adjusted": _deposit_adjusted,
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
                "and the experiment that produced it is served here in full beside the "
                f"{len(built) - len(refuted)} that survived. Every claim's falsifier result is "
                "computed from the measured figures rather than restated."
                if refuted
                else f"None of the {len(built)} registered claims was refuted by its own "
                "falsifier."
            ),
        },
        "experiments": built,
        "decision_impact": decision_impact_section(),
    }


# The notional and switching cost a reader sees first. Inputs, not observations — chosen as
# round numbers rather than derived from anything, and echoed on the output so a reader can
# apply their own instead.
DECISION_IMPACT_NOTIONALS_USD = (10_000.0, 100_000.0)
DECISION_IMPACT_SWITCHING_COST_USD = 25.0


def decision_impact_section() -> dict:
    """Whether the liquidity finding changes a decision, computed from the same frozen run.

    The liquidity experiment established that quoting gross overstates the rate a provider
    keeps. That is a fact about a percentage, and a percentage is not a thing anyone acts on.
    This section asks the harder question three ways and publishes all three answers,
    including the one that does not support the thesis.

    **It is post hoc and says so.** The registered experiment measured rate error; these three
    measures were written after that run existed, against the same frozen snapshot, so their
    result was knowable before the questions were fixed. That is a materially weaker footing
    than the registered work beside it and the distinction is stated rather than blurred — a
    genuinely pre-registered version needs a future snapshot nobody has seen yet.
    """
    from .decision_impact import (
        break_even_shift,
        dollars_at_notionals,
        ranking_reversals,
    )

    record = run("01-liquidity-arithmetic")
    pools = record["pools"]
    reversals = ranking_reversals(pools)
    dollars = dollars_at_notionals(pools, list(DECISION_IMPACT_NOTIONALS_USD))
    moves = break_even_shift(
        pools,
        notional_usd=DECISION_IMPACT_NOTIONALS_USD[0],
        switching_cost_usd=DECISION_IMPACT_SWITCHING_COST_USD,
    )
    return {
        "registration_state": "post_hoc",
        "registration_note": (
            "These three measures were written after the run they read, against the same "
            "frozen snapshot, so their outcome was already knowable when the questions were "
            "fixed. They are published on that footing and not as pre-registered findings. "
            "The experiments above are registered; this section is not."
        ),
        "dataset_ref": record["dataset_ref"],
        "dataset_sha256": record["dataset_sha256"],
        "ranking_reversals": reversals,
        "dollars_at_notionals": dollars,
        "break_even_shift": moves,
        "finding": (
            f"Over {reversals['denominator']} ordered pairs of the eligible pools, "
            f"{reversals['numerator']} change order between the gross ranking and the net "
            "one, and the pool ranked best is the same under both. So on the decision of "
            "which pool to be in, subtracting the protocol's cut changes nothing here — the "
            "measure that needs no assumption about position size is the one that found "
            "no effect, and it is reported first for that reason. What the error does change "
            "is what the position is worth and how long a move takes to repay: at a declared "
            f"${DECISION_IMPACT_NOTIONALS_USD[0]:,.0f} the median pool overstates annual fees "
            f"by ${dollars['notionals'][0]['median_annual_overstatement_usd']:,.2f}, and over "
            f"{moves['n_moves']} candidate moves the real payback arrives a median "
            f"{moves['median_days_later_than_gross_implies']:.2f} days later than the gross "
            "figures imply."
        ),
    }
