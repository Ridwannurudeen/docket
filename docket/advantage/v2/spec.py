"""The experiment, written down and hashed before any of it is run.

v1 records one run per task and says so. Its honest weakness is that everything about
the comparison — which metric, how many runs, what would have counted as a refutation —
was settled while the results were already visible. Nothing in that file lets a reader
tell a question asked in advance from one asked afterwards, and the two produce very
different reports from the same runs.

This module is the half that has to exist first. A `TaskSpec` names the claim, the exact
formula behind the metric, the nulls it will be measured against, how many runs are
planned, when the runs stop, and the result that would refute the claim — and then it is
frozen and hashed. Every later run record cites that hash. Editing the spec after the
runs come in is still possible; what is no longer possible is doing it quietly, because
the citation stops matching the file.

Construction refuses eight shapes outright, and a refusal here costs nothing while the
same shape published costs the whole report. A spec with one null shows an arm did
something but not that it was the mechanism the claim names rather than the setup around
it — and two rows naming the same null are still one null, as is a pair whose fields are
present but blank, so both are refused alongside it. A spec with an empty falsifier
states something no run could ever settle. A spec planning a single run per arm is v1
again, with no spread to report next to its number. A metric named without its formula
written out can be recomputed a different way once the results are in, and both recipes
answer to the same name in the report. Two more are refused for the same reason in a
different place: a blank claim leaves what was tested to be decided afterwards, and a
blank `dataset_sha256` leaves the inputs free to change under a path that still reads
the same.

Nothing here validates that the falsifier is a *good* one, or that a null is well
chosen. Those are arguments, and they are carried as text — `why_it_is_the_right_null`
is a field precisely so the argument travels with the spec and a reader can disagree
with it. Machine checks are for what a machine can actually establish: that every field
is present and says something, that two nulls are two, that the record cannot be edited
through a reference its caller kept, and that a file still hashes to the digest it
carries.

Hashes come from `hire.receipts.canonical_hash` — the same function, and so the same
recipe, that binds a hire receipt to its delivery and stamps v1's recorded outputs. The
saved file carries its own `spec_hash`, so a reader holding nothing but the file can
re-hash the rest of it and check the two agree. `load` makes exactly that check on the
way in: a spec edited on disk after it was registered raises there, rather than coming
back with a freshly computed digest and a citation that has quietly stopped matching.
"""

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from ...hire.receipts import canonical_hash

# What a null baseline has to say about itself: what it is, how to run it, and why it is
# the right thing to compare against. The third is the one that stops a null from being
# chosen after the results, and it is the one a machine can only check was written down.
BASELINE_FIELDS = frozenset({"name", "what_it_does", "why_it_is_the_right_null"})


@dataclass(frozen=True)
class TaskSpec:
    """One pre-registered experiment, fixed at construction.

    Frozen because the hash is quoted elsewhere. A record that could be edited in place
    would leave every citation of it pointing at something that no longer exists, and
    `null_baselines` is a tuple for the same reason rather than as a typing preference.
    Freezing alone would not have been enough: `metric` and the baselines are dicts, and
    a caller holding a reference could write through one after construction. So the
    record copies them on the way in, and the digest it registers with is the one it
    keeps for as long as it exists.
    """

    spec_id: str
    question: str
    category: str
    claim: str
    metric: dict
    null_baselines: tuple[dict, ...]
    dataset_ref: str
    dataset_sha256: str
    n_planned: int
    stopping_rule: str
    falsifier: str
    registered_at: str

    def __post_init__(self):
        # `frozen=True` stops these fields being rebound. It does not stop the dicts
        # behind them being written through a reference the caller kept, and this method
        # does not run a second time to notice. So the record takes its own copy before
        # it checks anything: what was checked is then what it holds, for good.
        object.__setattr__(self, "metric", deepcopy(self.metric))
        object.__setattr__(self, "null_baselines", deepcopy(self.null_baselines))
        if not self.claim.strip():
            raise ValueError(
                "spec: claim is empty — the runs would have nothing to be evidence for, "
                "and what they tested could be written down once they finished"
            )
        if not str(self.metric.get("formula", "")).strip():
            raise ValueError(
                f"spec: metric {self.metric.get('name', '<unnamed>')!r} carries no formula "
                "— a metric named but not written out can be recomputed a different way "
                "once the runs are in, under the same name"
            )
        if len(self.null_baselines) < 2:
            raise ValueError(
                f"spec: {len(self.null_baselines)} null baselines is fewer than two — one "
                "null shows the arm did something, and the second is what separates the "
                "mechanism the claim names from the setup around it"
            )
        for baseline in self.null_baselines:
            unsaid = {
                field for field in BASELINE_FIELDS if not str(baseline.get(field, "")).strip()
            }
            if unsaid:
                raise ValueError(
                    f"spec: null baseline {baseline.get('name', '<unnamed>')!r} leaves "
                    f"{sorted(unsaid)} missing or blank — a null nobody can re-run, or whose "
                    "choice is never argued, is a baseline that can be picked after the results"
                )
        names = [baseline["name"] for baseline in self.null_baselines]
        if len(set(names)) < len(names):
            raise ValueError(
                f"spec: null baselines {sorted(names)} are not distinct — the same null "
                "listed twice is one null, and it meets the count while leaving the "
                "comparison the second row was there to make unmade"
            )
        if not self.dataset_sha256.strip():
            raise ValueError(
                f"spec: dataset_sha256 is empty — {self.dataset_ref!r} would then mean "
                "whatever that path holds on the day somebody reads it, and the runs "
                "could not be checked against the inputs they were registered against"
            )
        if self.n_planned < 2:
            raise ValueError(
                f"spec: n_planned is {self.n_planned} — one run per arm is what v1 already "
                "records, and a single trial carries no spread to report next to it"
            )
        if not self.falsifier.strip():
            raise ValueError(
                "spec: falsifier is empty — a claim that names no result which would "
                "refute it is not a claim, and every run that came in would read as support"
            )

    @property
    def spec_hash(self) -> str:
        """SHA-256 over the registered fields, and nothing derived from them.

        It is what a run record cites, so it has to be reachable from the file alone and
        identical for a spec just built and the same spec read back off disk.
        """
        return canonical_hash(self._body())

    def _body(self) -> dict:
        return {
            "spec_id": self.spec_id,
            "question": self.question,
            "category": self.category,
            "claim": self.claim,
            "metric": dict(self.metric),
            # Plain lists and dicts, so the tuple this record holds in memory and the
            # array JSON gives it back cannot hash to two different digests.
            "null_baselines": [dict(baseline) for baseline in self.null_baselines],
            "dataset_ref": self.dataset_ref,
            "dataset_sha256": self.dataset_sha256,
            "n_planned": self.n_planned,
            "stopping_rule": self.stopping_rule,
            "falsifier": self.falsifier,
            "registered_at": self.registered_at,
        }

    def as_record(self) -> dict:
        return self._body() | {"spec_hash": self.spec_hash}


def save(spec: TaskSpec, path) -> None:
    """Write the spec, and its own hash with it, as sorted indented JSON with LF endings.

    Deterministic for the reason `harness.save` is: a committed spec that reformatted
    itself on every read would produce diffs that hide whether the registration changed.
    The digest goes in the file rather than beside it so the two cannot be separated.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(spec.as_record(), sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(blob + "\n", encoding="utf-8", newline="\n")


def load(path) -> TaskSpec:
    """Rebuild the spec from its registered fields, and refuse a file that has moved.

    The stored hash is not one of the fields, so it is recomputed from what the file
    holds and then compared against what the file claims. That comparison is the reason
    `save` puts the digest inside the file rather than beside it: separated, neither half
    can contradict the other. A file carrying no hash at all is rebuilt without the check
    — there is nothing there to disagree with — and a file missing a registered field
    raises rather than defaulting, because a half-read spec would be cited as a whole one.
    """
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    stored = record.pop("spec_hash", None)
    record["null_baselines"] = tuple(record["null_baselines"])
    spec = TaskSpec(**record)
    if stored is not None and stored != spec.spec_hash:
        raise ValueError(
            f"spec: {Path(path).name} carries spec_hash {stored} but its fields hash to "
            f"{spec.spec_hash} — the file was edited after it was registered, and every run "
            "record citing the first digest describes a spec that is no longer on disk"
        )
    return spec
