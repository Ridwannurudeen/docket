"""The paired experiment, registered before either arm runs.

v1 answers the sponsor's question — three tasks, each done once by hiring an agent and once
by hand — and it is the only report in this build that does. Its weakness is that each task
is a single pair, and that the metric and the framing were settled while the results were
already on screen. v2 fixed the second half for the wrong comparison: its repeated trials
are agent-against-null, it holds no human arm at all, and so it cannot be the artifact the
gate asks for. v3 is the pairing of v1 run as v2 taught us to run things.

Three things are different here, and each one exists because of a specific way the earlier
reports could be doubted.

**A family, not an anecdote.** `n_planned` is refused below three. One pair per task is what
v1 already publishes; a reader cannot tell a real difference from a lucky draw at n=1, and
the honest response to that is more cases rather than more confident prose about the one.

**The rubric is written before the outputs exist.** `quality_rubric` names its criteria and
what full marks and zero mean for each, and scoring is blinded: two evaluators, arms
randomised and unlabelled. Output quality is the one measure here that is a judgement, and
a judgement made while you know which arm you are looking at is not evidence. Time and cost
are clocked and recorded; neither is converted into the other, because an hourly rate is
the single assumption that would let this report produce whatever number it wanted.

**The inputs are locked in their own commit, and the spec says whether they are.** This is
the part v2 got wrong and disclosed rather than fixed: two of its three specifications
entered git together with their completed runs, so nothing but its own word separates them
from questions written afterwards. A live dataset cannot be hashed before it exists, so the
lock is two-stage and each stage is a commit of its own. Stage one registers the question,
the arms, the rubric, the selection rule and the falsifier — everything that decides what
counts as a result — while `inputs_sha256` is still empty. Stage two freezes the actual
cases and fills it in. `runnable` is false until then, and `assert_runnable` is what a
harness calls before it is allowed to run anything. The claim git can support is exactly
"the question predates the inputs, and the inputs predate the runs", and that is the claim
this makes checkable rather than asserted.

Hashes come from `hire.receipts.canonical_hash` — the same function that binds a hire
receipt and stamps v1's outputs, so a reader who can check one can check all of them.
"""

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from ...hire.receipts import canonical_hash

ARMS = ("agent", "manual")
ARM_FIELDS = frozenset({"what_it_does", "who_runs_it", "what_is_recorded"})
CRITERION_FIELDS = frozenset({"name", "full_marks_means", "zero_means"})
# Three is the smallest number that can show a spread rather than a pair of points. It is a
# floor, not a target: each family below plans five or twelve.
MIN_CASES = 3
MIN_EVALUATORS = 2
MIN_CRITERIA = 2


@dataclass(frozen=True)
class PairedSpec:
    """One registered agent-versus-human experiment, fixed at construction."""

    spec_id: str
    question: str
    category: str
    claim: str
    falsifier: str
    arms: dict
    case_selection: dict
    quality_rubric: dict
    scoring: dict
    measures: dict
    n_planned: int
    stopping_rule: str
    registered_at: str
    inputs_ref: str
    # Empty until the cases are frozen in their own commit. That emptiness is the whole
    # point of the field: it is what makes stage one legible as stage one.
    inputs_sha256: str = ""
    failure_policy: str = field(
        default=(
            "Every case that was started is published, including the ones where an arm failed "
            "or returned nothing. A failed case keeps its place in the denominator and is not "
            "re-run until it passes."
        )
    )

    def __post_init__(self):
        # Frozen stops rebinding, not writes through a reference the caller kept, and
        # __post_init__ does not run again to notice one. So the record takes its own copy
        # before it validates: what was checked is what it holds.
        for name in ("arms", "case_selection", "quality_rubric", "scoring", "measures"):
            object.__setattr__(self, name, deepcopy(getattr(self, name)))

        for name in ("claim", "falsifier", "stopping_rule", "question"):
            if not str(getattr(self, name)).strip():
                raise ValueError(
                    f"spec: {name} is empty — a paired run needs it fixed before the outputs "
                    "exist, or it can be written to fit them afterwards"
                )

        if tuple(sorted(self.arms)) != tuple(sorted(ARMS)):
            raise ValueError(
                f"spec: arms are {sorted(self.arms)} — this report compares exactly "
                f"{sorted(ARMS)}, because that is the comparison the gate asks for and the "
                "one v2 does not make"
            )
        for arm, body in self.arms.items():
            unsaid = {f for f in ARM_FIELDS if not str(body.get(f, "")).strip()}
            if unsaid:
                raise ValueError(
                    f"spec: the {arm} arm leaves {sorted(unsaid)} missing or blank — an arm "
                    "nobody can re-run is an arm whose procedure was decided while it ran"
                )

        if self.n_planned < MIN_CASES:
            raise ValueError(
                f"spec: n_planned is {self.n_planned}, fewer than {MIN_CASES} — one pair per "
                "task is what v1 already publishes, and it carries no spread to read the "
                "difference against"
            )
        if not str(self.case_selection.get("rule", "")).strip():
            raise ValueError(
                "spec: case_selection.rule is blank — without it the cases can be chosen "
                "once the results are visible, which is the objection this whole file exists "
                "to answer"
            )

        criteria = self.quality_rubric.get("criteria") or []
        if len(criteria) < MIN_CRITERIA:
            raise ValueError(
                f"spec: the rubric has {len(criteria)} criteria, fewer than {MIN_CRITERIA} — "
                "a single criterion is a preference, and output quality is the one measure "
                "here that is a judgement rather than a reading"
            )
        for criterion in criteria:
            unsaid = {
                f for f in CRITERION_FIELDS if not str(criterion.get(f, "")).strip()
            }
            if unsaid:
                raise ValueError(
                    f"spec: rubric criterion {criterion.get('name', '<unnamed>')!r} leaves "
                    f"{sorted(unsaid)} missing or blank — a criterion without its anchors is "
                    "scored differently by two people and differently by one person twice"
                )
        if not str(self.quality_rubric.get("scale", "")).strip():
            raise ValueError(
                "spec: the rubric names no scale, so its scores have no units"
            )

        if int(self.scoring.get("evaluators", 0)) < MIN_EVALUATORS:
            raise ValueError(
                f"spec: {self.scoring.get('evaluators')} evaluator(s) is fewer than "
                f"{MIN_EVALUATORS} — one scorer's judgement has nothing to disagree with it"
            )
        if self.scoring.get("blinded") is not True:
            raise ValueError(
                "spec: scoring is not blinded — a quality judgement made while you can see "
                "which arm produced the output is not evidence about the arms"
            )
        if not str(self.scoring.get("disagreement", "")).strip():
            raise ValueError(
                "spec: the rubric does not say what happens when the two evaluators disagree, "
                "so it would be settled after the disagreement is known"
            )

        for measure in ("time", "cost"):
            if not str(self.measures.get(measure, "")).strip():
                raise ValueError(
                    f"spec: measures.{measure} is blank — the gate asks for it by name, and "
                    "how it is clocked has to be fixed before the clock starts"
                )

    @property
    def runnable(self) -> bool:
        """Whether the cases are frozen. False through the whole of stage one."""
        return bool(self.inputs_sha256.strip())

    @property
    def spec_hash(self) -> str:
        return canonical_hash(self._body())

    def _body(self) -> dict:
        return {
            "spec_id": self.spec_id,
            "question": self.question,
            "category": self.category,
            "claim": self.claim,
            "falsifier": self.falsifier,
            "arms": dict(self.arms),
            "case_selection": dict(self.case_selection),
            "quality_rubric": dict(self.quality_rubric),
            "scoring": dict(self.scoring),
            "measures": dict(self.measures),
            "n_planned": self.n_planned,
            "stopping_rule": self.stopping_rule,
            "failure_policy": self.failure_policy,
            "registered_at": self.registered_at,
            "inputs_ref": self.inputs_ref,
            "inputs_sha256": self.inputs_sha256,
        }

    def as_record(self) -> dict:
        return self._body() | {"spec_hash": self.spec_hash, "runnable": self.runnable}


def assert_runnable(spec: PairedSpec) -> None:
    """Refuse to run a spec whose cases are not yet frozen.

    The harness calls this before the first arm. Without it the two-stage lock is a comment:
    nothing would stop a run against inputs chosen the same afternoon, which is the shape
    v2 disclosed about two of its three experiments.
    """
    if not spec.runnable:
        raise ValueError(
            f"spec {spec.spec_id!r} has no locked inputs — {spec.inputs_ref!r} must be frozen "
            "and its digest registered in its own commit before either arm runs, or git "
            "cannot show the cases predate the results"
        )


def save(spec: PairedSpec, path) -> None:
    """Write the spec and its own digest, deterministically, with LF endings."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(spec.as_record(), sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(blob + "\n", encoding="utf-8", newline="\n")


def load(path) -> PairedSpec:
    """Rebuild a spec and refuse a file that has moved under its own hash."""
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    stored = record.pop("spec_hash", None)
    record.pop("runnable", None)  # derived, never an input
    spec = PairedSpec(**record)
    if stored is not None and stored != spec.spec_hash:
        raise ValueError(
            f"spec {spec.spec_id!r} does not hash to the digest it carries: the file says "
            f"{stored} and its contents give {spec.spec_hash}. It was edited after it was "
            "registered, and every run citing the old digest now cites something that no "
            "longer exists."
        )
    return spec
