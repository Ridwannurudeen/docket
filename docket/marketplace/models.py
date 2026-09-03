"""The vocabulary a marketplace needs and Docket did not have.

Docket ran two halves that could not see each other. `hire.catalogue` knew what a
service costs and how to run it, and nothing about who it is on chain or what job it
does. The registry API knew what agents declared on chain, and nothing about how to
hire one. A reader who found an agent could not activate it, and a reader who
activated a service could not inspect it. The types here are the seam.

Three rules are enforced by the constructors rather than by review, because each one
has already been broken somewhere in this project:

`Metric` refuses a share without its base. A rate published against the wrong
denominator is not a rounding error, it is a different claim — 13 of 35 read as "of
probed" when 14 were probed says something Docket never measured.

`EvidenceRef` refuses a URL Docket does not serve. Evidence a reader cannot open from
this origin is a citation nobody can check, and it would put a third-party request on
a site that makes none.

`ServiceRecord` refuses a service that cannot be hired and a record with no stated
limitations. The first keeps the two halves joined; the second is the sentence a
marketplace is most tempted to leave out.

What is NOT enforced here is a category on anything Docket does not run. The ERC-8004
record carries nothing that says what job an agent does, so Docket declares a category
for its own services and assigns none to anybody else's — see `CATEGORY_DECLARATION`.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from ..hire.catalogue import SERVICES as HIRE_SERVICES


# Not `enum.StrEnum`: that changes what `str(member)` and f-string interpolation
# produce, from the qualified `Category.MEMBER` a log line or an error message shows to
# the bare value. The value already crosses JSON through `.value`, so the substitution
# would trade a diagnostic for nothing.
class Category(str, Enum):  # noqa: UP042
    """BNB's four job categories, and exactly those four.

    A str enum so a query parameter typed as this rejects anything else at the door
    and names the four permitted values in the 422 it returns.
    """

    REBALANCING = "rebalancing"
    GRID_TRADING = "grid_trading"
    YIELD_OPTIMISATION = "yield_optimisation"
    HEALTH_FACTOR = "health_factor"


@dataclass(frozen=True)
class CategoryJob:
    """One category as a person reads it: the job it gets done, and what an agent doing
    that job actually does. The label leads, because a stranger looking for help has a
    job in mind and not a taxonomy."""

    category: Category
    job: str
    does: str


# Declared order, fixed here and served in it. An order that varies between responses
# is a ranking a reader will read as one.
CATEGORIES: tuple[CategoryJob, ...] = (
    CategoryJob(
        category=Category.REBALANCING,
        job="Keep LP earning",
        does=(
            "Reads or manages a concentrated-liquidity position so it keeps earning fees "
            "instead of sitting outside the range it was set in."
        ),
    ),
    CategoryJob(
        category=Category.GRID_TRADING,
        job="Run a capped grid",
        does=(
            "Places and maintains a grid of orders inside a price band, with the capital it "
            "may commit bounded before it starts."
        ),
    ),
    CategoryJob(
        category=Category.YIELD_OPTIMISATION,
        job="Move idle liquidity",
        does=(
            "Finds capital earning less than it could elsewhere and states what moving it "
            "would cost, in gas and in what is given up."
        ),
    ),
    CategoryJob(
        category=Category.HEALTH_FACTOR,
        job="Protect a loan",
        does=(
            "Watches a lending position's health factor and acts, or tells the borrower to, "
            "before the position is liquidated."
        ),
    ),
)

# What "activation" means for a service, in the reader's terms. Closed: a card that
# says what happens when you press the control has to draw from a vocabulary, or every
# service invents its own promise. All three services Docket runs today are one_shot.
ACTIVATIONS: dict[str, str] = {
    "one_shot": "Runs once when you activate it and hands back a result.",
    "monitor": "Watches a position and reports back on a schedule you set.",
    "policy_action": "Acts on chain within a policy you set before it starts.",
}

# One kind, because one kind is all Docket serves as evidence today: the recorded
# hired-vs-manual experiments at /advantage, both arms in full and hash-bound. Adding
# a kind means adding something Docket actually publishes to point at.
EVIDENCE_KINDS = frozenset({"advantage_task"})

EvidenceModality = Literal[
    "live_read", "preview", "historical", "paired_benchmark", "replay"
]
EVIDENCE_MODALITIES = frozenset(
    {"live_read", "preview", "historical", "paired_benchmark", "replay"}
)

# How a share of a population gets written. Matched as words inside the unit rather than
# as an exact value, because an allowlist of exact spellings is open at the back: "pct" is
# as much a rate as "%", and a spelling nobody thought to list would construct with no
# base at all. A unit naming a share is unreadable without what it was divided by, so the
# base is required rather than encouraged — and the guard only ever fires where no
# denominator was supplied, so the cost of catching a count that happens to read like a
# rate is naming its population, which was the discipline anyway.
SHARE_WORDS = frozenset(
    {
        "percent",
        "percentage",
        "pct",
        "share",
        "rate",
        "ratio",
        "proportion",
        "bps",
        "basis points",
        "per cent",
        "per mille",
        "permille",
    }
)


def is_share_unit(unit: str) -> bool:
    """Whether this unit expresses a share of something rather than a quantity of it."""
    lowered = unit.lower()
    if "%" in lowered:
        return True
    return any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in SHARE_WORDS)


def _require_text(value: str, field: str, subject: str) -> None:
    if not value.strip():
        raise ValueError(f"{subject}: {field} is required and must not be blank")


@dataclass(frozen=True)
class Metric:
    """One observed figure, carried with everything needed to read it.

    `window` is what period or run the figure covers, `observed_at` when it was taken,
    and `method` how — the same discipline every count on /stats travels under. A
    figure without those three is a number a reader can neither date nor contest.
    """

    name: str
    unit: str
    window: str
    observed_at: str
    method: str
    value: float | None = None
    numerator: int | None = None
    denominator: int | None = None

    def __post_init__(self) -> None:
        for field in ("name", "unit", "window", "observed_at", "method"):
            _require_text(getattr(self, field), field, f"metric {self.name!r}")
        # Halves of a fraction, never one of them: a numerator alone is the same
        # unreadable figure as a rate with no base, written the other way round.
        if (self.numerator is None) != (self.denominator is None):
            raise ValueError(
                f"metric {self.name!r}: a numerator and its denominator travel together"
            )
        if is_share_unit(self.unit) and self.denominator is None:
            raise ValueError(
                f"metric {self.name!r}: a share in {self.unit!r} needs the population it is "
                "a share of. Counts may stand alone; rates may not."
            )
        if self.value is None and self.numerator is None:
            raise ValueError(f"metric {self.name!r}: carries no figure at all")

    def render(self) -> str:
        """Text that cannot be quoted without its denominator, because the denominator is
        inside the string."""
        if self.numerator is None:
            return f"{self.value:g} {self.unit}"
        if is_share_unit(self.unit):
            share = f" ({self.value:g}%)" if self.value is not None else ""
            return f"{self.numerator} of {self.denominator}{share}"
        return f"{self.numerator} of {self.denominator} {self.unit}"


@dataclass(frozen=True)
class EvidenceRef:
    """A pointer at something Docket already serves and a reader can open now."""

    kind: str
    url: str
    label: str

    def __post_init__(self) -> None:
        if self.kind not in EVIDENCE_KINDS:
            raise ValueError(
                f"evidence kind {self.kind!r} is not one of {sorted(EVIDENCE_KINDS)}"
            )
        if not self.url.startswith("/"):
            raise ValueError(
                f"evidence url {self.url!r} must be a path this origin serves: evidence a "
                "reader cannot open here is a citation nobody can check"
            )
        _require_text(self.label, "label", f"evidence {self.url!r}")


@dataclass(frozen=True)
class ServiceRecord:
    """One service as a marketplace shows it: the offer, the identity behind it, the job
    Docket declares it does, what has been observed of it, and what it cannot do.

    The offer itself is read through to `hire.catalogue` rather than copied. Two copies
    of a price or an input schema is two things to keep in step, and the one that goes
    stale is whichever the reader happens to be looking at.
    """

    service_id: str
    category: Category | None
    # The BSC ERC-8004 identity this service is bound to, lowercased exactly as the
    # snapshot stores it so /agents/{agent_id} resolves. None where no identity has
    # been registered — which is most of them, and is said rather than left blank.
    agent_id: str | None
    registration_uri: str | None
    activation: str
    evidence_modality: EvidenceModality
    metrics: tuple[Metric, ...]
    evidence: tuple[EvidenceRef, ...]
    limitations: str

    def __post_init__(self) -> None:
        if self.service_id not in HIRE_SERVICES:
            raise ValueError(
                f"{self.service_id!r} is not in the hire catalogue: a marketplace record "
                "for a service nobody can call is the split-brain this package closes"
            )
        if self.activation not in ACTIVATIONS:
            raise ValueError(
                f"{self.service_id}: activation {self.activation!r} is not one of "
                f"{sorted(ACTIVATIONS)}"
            )
        if self.evidence_modality not in EVIDENCE_MODALITIES:
            raise ValueError(
                f"{self.service_id}: evidence_modality {self.evidence_modality!r} is not one "
                f"of {sorted(EVIDENCE_MODALITIES)}"
            )
        _require_text(self.limitations, "limitations", self.service_id)

    @property
    def offer(self):
        """The hire catalogue entry this record describes."""
        return HIRE_SERVICES[self.service_id]

    @property
    def name(self) -> str:
        return self.offer.name

    @property
    def what_you_get(self) -> str:
        return self.offer.what_you_get

    @property
    def input_schema(self) -> dict:
        return self.offer.input_schema

    @property
    def price_display(self) -> str:
        return self.offer.price_display

    @property
    def price_atomic(self) -> int:
        return self.offer.price_atomic

    @property
    def asset(self) -> str:
        return self.offer.asset

    @property
    def paid_stock(self) -> bool:
        return self.offer.paid_stock

    @property
    def stock_status(self) -> str:
        return self.offer.stock_status

    @property
    def admission(self) -> dict[str, bool]:
        return {
            "fresh_paired_benchmark": self.offer.admission.fresh_paired_benchmark,
            "cold_canary": self.offer.admission.cold_canary,
            "decision_grade_presenter": self.offer.admission.decision_grade_presenter,
            "true_settlement": self.offer.admission.true_settlement,
        }

    @property
    def typical_seconds(self) -> int:
        return self.offer.typical_seconds

    @property
    def activation_means(self) -> str:
        return ACTIVATIONS[self.activation]

    @property
    def identity_line(self) -> str:
        """Said in both directions. An unbound service that simply omitted the field would
        be read as one whose identity nobody bothered to print."""
        if self.agent_id is None:
            return (
                "No BSC identity bound yet. Docket runs this service from its own host and "
                "has registered no ERC-8004 agent for it, so there is no on-chain record of "
                "it to read."
            )
        return (
            f"Bound to the BSC ERC-8004 agent {self.agent_id}. This registration is not "
            "an endorsement, evidence of paid stock, or evidence that the service "
            "produced a result."
        )
