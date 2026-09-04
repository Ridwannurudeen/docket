"""The four paid-stock facts, derived from durable artifacts on every request.

Three of the four limbs used to be constants a developer typed into the catalogue. A
constant is a claim about the world that stops being checked the moment it is written,
and this file is the correction: every limb below is recomputed from something a reader
can open — a canary row, a settled payment row, a registered benchmark artifact — and
`admission_evidence` names the exact artifact that satisfied it.

**`fresh_paired_benchmark` — the rule, in full.**

The written definition everywhere it appears (`docs/submission/claims-checklist.md` E-19,
`docs/operational-evidence.md`, `docket/api/static/SKILL.md`) is "fresh paired evidence" /
"produces a paired benchmark". Nothing in it requires a particular verdict, so nothing
here does either: a benchmark that refuted its own claim is still a paired benchmark, and
requiring `not_refuted` would make the limb mean "we passed" rather than "we measured".

An artifact satisfies the limb when all three hold:

1. It is *paired* — two arms, agent and manual, over the same task.
2. Both arms reached a terminal state and produced an actual output. A v1 experiment
   qualifies when both arms carry an output and neither carries an error; a v3 family
   qualifies when its reconstructed state is one of `complete_unscored`, `refuted` or
   `not_refuted`, which are the three the report reaches only after every scheduled
   primary is terminal.
3. It was observed inside the disclosed window — `PAIRED_EVIDENCE_WINDOW_DAYS` days from
   the artifact's own observation date. For a v1 experiment that date is the agent arm's
   receipt `delivered_at`, the only timestamp the file carries; the manual arm carries
   none, which is stated rather than papered over. For a v3 family it is the newest
   `recorded_at` on its ledger, which is the moment the last thing that happened to it
   happened. A future-dated artifact fails, exactly as a future-dated canary does.

The window is what makes the limb *fresh* rather than merely true once. It is disclosed
on the evidence, so a reader can see both the date the artifact carries and the instant
the limb expires without reading this file.

**`true_settlement`** is a `hire_payments` row that reached `settled` — not
`settlement_unknown`, which is a payment whose facilitator answer never came back.
Docket's own operator-run canary settles through the same rail as anybody else, so its
row counts; the evidence says whose wallet paid, so a settlement Docket paid for itself
cannot read as a third party's purchase.

**`cold_canary`** is unchanged: the latest run must have passed and have finished inside
`CANARY_MAX_AGE_SECONDS`.

**`decision_grade_presenter`** is the one limb still stated per service in the catalogue.
It is a property of how a result is written, which nothing in the store observes.
"""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from .catalogue import CONTROLLED_EXAMPLE_WALLET, PaidStockAdmission, Service

# A daily run gets twelve hours of scheduling and incident-recovery margin. Past that,
# yesterday's observation cannot admit paid work today.
CANARY_MAX_AGE_SECONDS = 36 * 60 * 60
# How long a paired benchmark stays fresh. Thirty days is a stated choice, not a derived
# one, and it is published on every evidence record so a reader can apply their own.
PAIRED_EVIDENCE_WINDOW_DAYS = 30
PAIRED_EVIDENCE_WINDOW_SECONDS = PAIRED_EVIDENCE_WINDOW_DAYS * 24 * 60 * 60
# The three v3 states the report reaches only once every scheduled primary is terminal.
# `complete_unscored` is included because the pairing completed and only the scoring did
# not: the arms ran, and that is what "paired benchmark" names.
TERMINAL_V3_STATES = ("complete_unscored", "refuted", "not_refuted")


def _utc(value) -> datetime | None:
    """One timestamp read off an artifact, or nothing.

    Refused rather than converted when the offset is not zero, which is the rule the
    canary limb has always applied and is now applied to every artifact this file reads.
    A naive timestamp is a moment in an unstated zone. A `+01:00` one is a moment written
    by something that was not following the contract these records are stored under, and
    silently converting it would mean the gate could not tell a correct record from a
    record it happened to be able to repair.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed


def _now(now: datetime | None) -> datetime | None:
    observed = now or datetime.now(UTC)
    if observed.tzinfo is None:
        return None
    return observed.astimezone(UTC)


def _within(observed: datetime, now: datetime, seconds: int) -> bool:
    age = (now - observed).total_seconds()
    return 0 <= age <= seconds


def _fresh_passed_canary(latest_run: dict | None, now: datetime | None = None) -> bool:
    if not isinstance(latest_run, dict) or latest_run.get("verdict") != "passed":
        return False
    finished = _utc(latest_run.get("finished_at"))
    observed_now = _now(now)
    if finished is None or observed_now is None:
        return False
    return _within(finished, observed_now, CANARY_MAX_AGE_SECONDS)


def _canary_evidence(latest_run: dict | None, passed: bool) -> str:
    if passed:
        return (
            f"canary run {latest_run.get('id', '?')} passed at "
            f"{latest_run.get('finished_at')}, inside the {CANARY_MAX_AGE_SECONDS}-second "
            "freshness limit"
        )
    if not isinstance(latest_run, dict) or not latest_run:
        return "no canary run has ever been recorded for this service"
    verdict = latest_run.get("verdict")
    if verdict != "passed":
        return (
            f"the latest canary run {latest_run.get('id', '?')} is {verdict!r}, and only "
            "a passed run opens this limb"
        )
    return (
        f"the latest passed canary run {latest_run.get('id', '?')} finished at "
        f"{latest_run.get('finished_at')!r}, which is absent, malformed, not UTC, "
        f"future-dated, or older than the {CANARY_MAX_AGE_SECONDS}-second limit"
    )


def _v1_candidate(service_id: str, experiments) -> tuple[dict, datetime] | None:
    """The newest v1 experiment that is paired, complete, and about this service."""
    best: tuple[dict, datetime] | None = None
    for experiment in experiments or ():
        if not isinstance(experiment, dict):
            continue
        agent = experiment.get("agent_arm") or {}
        manual = experiment.get("manual_arm") or {}
        if agent.get("error") is not None or manual.get("error") is not None:
            continue
        output = agent.get("output")
        if not isinstance(output, dict) or manual.get("output") is None:
            continue
        receipt = output.get("receipt") or {}
        if receipt.get("service") != service_id:
            continue
        delivered = _utc(receipt.get("delivered_at"))
        if delivered is None:
            continue
        if best is None or delivered > best[1]:
            best = (experiment, delivered)
    return best


def _v3_candidate(service_id: str, report: dict | None) -> tuple[dict, datetime] | None:
    """The newest terminal v3 family registered for this service."""
    if not isinstance(report, dict):
        return None
    best: tuple[dict, datetime] | None = None
    for family in report.get("families") or ():
        if family.get("state") not in TERMINAL_V3_STATES:
            continue
        protocol = (family.get("spec") or {}).get("execution_protocol") or {}
        if protocol.get("agent_service_id") != service_id:
            continue
        recorded = [
            moment
            for moment in (
                _utc(event.get("recorded_at")) for event in family.get("ledger") or ()
            )
            if moment is not None
        ]
        if not recorded:
            continue
        newest = max(recorded)
        if best is None or newest > best[1]:
            best = (family, newest)
    return best


def _paired_benchmark(
    service_id: str,
    *,
    v3_report: dict | None,
    v1_experiments,
    now: datetime | None,
) -> tuple[bool, str]:
    """Whether a paired benchmark for this service was observed inside the window.

    v3 is preferred over v1 when both are fresh, because a v3 family is registered before
    its inputs are locked and a v1 experiment is not — but the limb is the same limb
    either way, and the evidence says which artifact opened it.
    """
    observed_now = _now(now)
    if observed_now is None:
        return False, "the observation time supplied for this decision is not UTC"

    found: list[str] = []
    v3 = _v3_candidate(service_id, v3_report)
    if v3 is not None:
        family, moment = v3
        expires = moment + timedelta(seconds=PAIRED_EVIDENCE_WINDOW_SECONDS)
        if _within(moment, observed_now, PAIRED_EVIDENCE_WINDOW_SECONDS):
            return True, (
                f"v3 family {family['spec_id']} is {family['state']} with both arms "
                f"scheduled and every primary terminal; its ledger's newest event is "
                f"{moment.isoformat()}, inside the disclosed "
                f"{PAIRED_EVIDENCE_WINDOW_DAYS}-day window, which closes at "
                f"{expires.isoformat()}"
            )
        found.append(
            f"v3 family {family['spec_id']} is {family['state']} but its newest ledger "
            f"event is {moment.isoformat()}, outside the disclosed "
            f"{PAIRED_EVIDENCE_WINDOW_DAYS}-day window"
        )
    elif v3_report is None:
        found.append("the v3 report could not be reconstructed for this decision")
    else:
        found.append(
            f"no v3 family registered for {service_id} is in a terminal state among "
            f"{list(TERMINAL_V3_STATES)}"
        )

    v1 = _v1_candidate(service_id, v1_experiments)
    if v1 is not None:
        experiment, moment = v1
        expires = moment + timedelta(seconds=PAIRED_EVIDENCE_WINDOW_SECONDS)
        payment = (
            ((experiment.get("agent_arm") or {}).get("output") or {}).get("receipt")
            or {}
        ).get("payment") or {}
        tier = payment.get("status") or "unstated"
        if _within(moment, observed_now, PAIRED_EVIDENCE_WINDOW_SECONDS):
            return True, (
                f"v1 experiment {experiment.get('task_id')} carries both arms with "
                f"outputs and no error; its agent arm was delivered at "
                f"{moment.isoformat()} on the {tier!r} tier — the only timestamp in the "
                "file, the manual arm carries none — which is inside the disclosed "
                f"{PAIRED_EVIDENCE_WINDOW_DAYS}-day window, closing at "
                f"{expires.isoformat()}"
            )
        found.append(
            f"v1 experiment {experiment.get('task_id')} is paired and complete but its "
            f"agent arm was delivered at {moment.isoformat()}, outside the disclosed "
            f"{PAIRED_EVIDENCE_WINDOW_DAYS}-day window"
        )
    else:
        found.append(f"no v1 experiment names {service_id} on a complete pair of arms")
    return False, "; ".join(found)


def _settlement(service_id: str, store) -> tuple[bool, str]:
    """Whether one hire of this service has ever reached `settled`."""
    if store is None:
        return False, (
            "no payment store was supplied for this decision, so no settlement could be "
            "read and none is assumed"
        )
    payment = store.latest_settled_payment(service_id)
    if not payment:
        return False, (
            f"no hire_payments row for {service_id} has reached 'settled'. A row left at "
            "'settlement_unknown' is a payment whose facilitator answer never came back "
            "and is not counted"
        )
    payer = str(payment.get("payer") or "")
    whose = (
        "Docket's own operator-run canary, not a third party's purchase"
        if payer.lower() == CONTROLLED_EXAMPLE_WALLET.lower()
        else f"payer {payer}, which is not Docket's published operator address"
    )
    return True, (
        f"hire payment {payment.get('payment_id')} settled {payment.get('amount')} of "
        f"{payment.get('asset')} at {payment.get('updated_at')} in transaction "
        f"{payment.get('transaction_id')} — {whose}"
    )


@dataclass(frozen=True)
class AdmissionResolution:
    """The four facts, and the artifact behind each one."""

    admission: PaidStockAdmission
    evidence: dict[str, str]

    @property
    def passes(self) -> bool:
        return self.admission.passes


def resolve_admission(
    service: Service,
    latest_run: dict | None,
    *,
    store=None,
    v3_report: dict | None = None,
    v1_experiments=None,
    now: datetime | None = None,
) -> AdmissionResolution:
    """Recompute all four admission facts from durable state, with their evidence.

    Every keyword defaults to "not supplied", and a limb whose source was not supplied is
    false with the evidence saying so. That is the safe direction: a caller who forgot to
    pass the store gets a service that is not for sale, never one that is for sale on a
    fact nobody checked.
    """
    paired, paired_why = _paired_benchmark(
        service.id, v3_report=v3_report, v1_experiments=v1_experiments, now=now
    )
    canary = _fresh_passed_canary(latest_run, now)
    settled, settled_why = _settlement(service.id, store)
    return AdmissionResolution(
        admission=replace(
            service.admission,
            fresh_paired_benchmark=paired,
            cold_canary=canary,
            true_settlement=settled,
        ),
        evidence={
            "fresh_paired_benchmark": paired_why,
            "cold_canary": _canary_evidence(latest_run, canary),
            "decision_grade_presenter": (
                "stated for this service in docket/hire/catalogue.py: it is a property of "
                "how a result is written, which nothing in the store observes"
                if service.admission.decision_grade_presenter
                else "not stated for this service in docket/hire/catalogue.py"
            ),
            "true_settlement": settled_why,
            "window": (
                f"a paired benchmark stays fresh for {PAIRED_EVIDENCE_WINDOW_DAYS} days "
                f"from its own observation date; a canary for "
                f"{CANARY_MAX_AGE_SECONDS} seconds from its finish"
            ),
        },
    )
