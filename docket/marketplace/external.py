"""Agents Docket did not build, listed without pretending Docket measured them.

`registry.py` holds the six services Docket runs. This holds everybody else: an
ERC-8004 registration on BSC, whatever endpoints it names, and — separately, never
mixed in — what Docket has actually observed of it.

Three separations are load-bearing here, and each is a field rather than a convention.

`declared_category` and `classified_category` are kept apart. The first is what the
registration itself says; the second is what Docket's rule table read out of the
capability text. `capability_source` names which one the category came from, so a label
Docket inferred can never be quoted as one the agent declared. This is the one place
Docket does put a category on somebody else's agent, and it is why the source travels
with it. `registry.CATEGORY_DECLARATION` is the sentence that describes both layers to a
reader, and it names this one explicitly: a classified category is a reading of published
text, labelled as a reading.

`classify` never guesses past its rule table. The table is data, printed below; a term
that is not in it does not match; and where two categories both match, the decision is
the written margin rule in `classify` and nothing else. A tie assigns no category, and
every rationale names the losing side, so a reader can see what the rule decided against.

`verification` is a whole object rather than a boolean. A listing exists at level None —
seen in the registry index, nothing observed — and moves only when
`verification.verify_listing` records evidence for a level. `hireable` is False until
`docket_tested`, so a listing cannot be sold on the strength of having been indexed.

Inside that object, `payment_tested` is its own boolean and is never inferred from the
level. `docket_tested` means one thing only — a sample invocation came back as a
schema-valid structured result — and it hangs off `live` rather than off
`payment_tested`, so a listing can stand at `docket_tested` with `payment_tested: false`.
That is not a contradiction; it is two facts a single ordered level cannot state
together, so both are serialised, together with the evidence row behind the boolean.
"""

import json
import re
from dataclasses import dataclass
from typing import Literal

from .models import Category

# Ordered weakest to strongest. `verification.py` runs them; the vocabulary lives here
# because a listing carries a level and this module defines a listing.
LEVELS: tuple[str, ...] = (
    "registered",
    "endpoint_detected",
    "live",
    "payment_tested",
    "docket_tested",
    "docket_verified",
)
LEVEL_ORDER = {name: index for index, name in enumerate(LEVELS)}

CAPABILITY_SOURCES = ("provider_declared", "registration_metadata", "docket_classified")

# Endpoint kinds another agent could invoke. A `web` link is a homepage: it is recorded
# on the listing because it is what the registration says, and it is not enough to reach
# `endpoint_detected`, because "the marketing site answered" is not "the service answered".
INVOCABLE_KINDS = ("a2a", "mcp")

# The rule table, in full. Every rule is one of exactly two kinds, and which kind it is
# is written in the rule rather than inferred:
#
#   "health factor"   whole phrase, bounded both ends: \bhealth factor\b
#   "rebalanc*"       stem, bounded at the front only: \brebalanc
#
# Stems exist so one rule covers rebalance / rebalances / rebalancing / rebalanced
# without four entries drifting apart. Nothing else is consulted, nothing is stemmed
# automatically, and a term not in this table does not match.
#
# Terms are the vocabulary of the JOB, never of a venue. "Venus" is deliberately absent:
# on 2026-09-03 the twenty BSC agents matching it split between lending-health monitors
# and yield rankers, so the protocol name identifies neither shelf. The same reasoning
# keeps "PancakeSwap", "BSC" and "DeFi" out.
CATEGORY_RULES: dict[Category, tuple[str, ...]] = {
    Category.REBALANCING: (
        "rebalanc*",
        "reposition*",
        "out of range",
        "out-of-range",
        "range order*",
        "lp range*",
        "liquidity range*",
        "concentrated liquidity",
        "liquidity position*",
        "lp position*",
        "position manager",
    ),
    Category.GRID_TRADING: (
        "grid*",
        "order ladder*",
        "ladder of orders",
    ),
    Category.YIELD_OPTIMISATION: (
        "yield optimi*",
        "yield router*",
        "yield aggregat*",
        "yield farming",
        "yield strateg*",
        "apr",
        "apy",
        "supply rate*",
        "borrow rate*",
        "rate gap*",
        "highest rate",
        "best available rate",
        "route liquidity",
        "idle capital",
        "idle liquidity",
    ),
    Category.HEALTH_FACTOR: (
        "health factor*",
        "liquidat*",
        "collateral ratio*",
        "borrow limit*",
        "lending position*",
        "loan to value",
        "ltv",
        "margin call*",
    ),
}

# What a registration may say about itself that Docket reads as a declaration rather than
# as prose. Keys are matched case-insensitively after stripping separators, so
# "Yield Optimisation", "yield_optimization" and "YIELD-OPTIMISATION" all land.
_DECLARED_CATEGORY_ALIASES: dict[str, Category] = {
    "rebalancing": Category.REBALANCING,
    "rebalance": Category.REBALANCING,
    "liquidityrebalancing": Category.REBALANCING,
    "gridtrading": Category.GRID_TRADING,
    "grid": Category.GRID_TRADING,
    "yieldoptimisation": Category.YIELD_OPTIMISATION,
    "yieldoptimization": Category.YIELD_OPTIMISATION,
    "yield": Category.YIELD_OPTIMISATION,
    "healthfactor": Category.HEALTH_FACTOR,
    "healthfactormonitoring": Category.HEALTH_FACTOR,
    "liquidationprotection": Category.HEALTH_FACTOR,
}

_SEPARATORS = re.compile(r"[\s._/\-]+")


def _normalise_declared(value: str) -> str:
    return _SEPARATORS.sub("", value).strip().lower()


def capability_text(metadata: dict) -> str:
    """Everything a registration says about what the agent does, as one string.

    Registry-supplied JSON is arbitrary, so every field is read defensively and a shape
    that is not what it should be contributes nothing rather than raising.
    """
    parts: list[str] = []
    for key in ("name", "description", "capabilities", "summary"):
        value = metadata.get(key)
        if isinstance(value, str):
            parts.append(value)
    for key in ("tags", "categories", "keywords"):
        value = metadata.get(key)
        if isinstance(value, (list, tuple)):
            parts.extend(item for item in value if isinstance(item, str))
    skills = metadata.get("skills")
    if isinstance(skills, (list, tuple)):
        for skill in skills:
            if isinstance(skill, str):
                parts.append(skill)
            elif isinstance(skill, dict):
                parts.extend(
                    str(skill.get(key))
                    for key in ("id", "name", "description")
                    if isinstance(skill.get(key), str)
                )
    services = metadata.get("services")
    if isinstance(services, dict):
        for service in services.values():
            if not isinstance(service, dict):
                continue
            tools = service.get("tools")
            if isinstance(tools, (list, tuple)):
                parts.extend(tool for tool in tools if isinstance(tool, str))
            skill_list = service.get("skills")
            if isinstance(skill_list, (list, tuple)):
                for skill in skill_list:
                    if isinstance(skill, dict) and isinstance(skill.get("name"), str):
                        parts.append(skill["name"])
    return " ".join(parts)


def _rule_pattern(term: str) -> str:
    """One rule as a regex. A trailing `*` drops the closing boundary; nothing else does."""
    if term.endswith("*"):
        return r"\b" + re.escape(term[:-1])
    return r"\b" + re.escape(term) + r"\b"


_COMPILED_RULES: dict[Category, tuple[tuple[str, "re.Pattern[str]"], ...]] = {
    category: tuple((term, re.compile(_rule_pattern(term))) for term in terms)
    for category, terms in CATEGORY_RULES.items()
}


def _matched_terms(text: str) -> dict[Category, tuple[str, ...]]:
    lowered = text.lower()
    matches: dict[Category, tuple[str, ...]] = {}
    for category, rules in _COMPILED_RULES.items():
        hits = tuple(term for term, pattern in rules if pattern.search(lowered))
        if hits:
            matches[category] = hits
    return matches


def declared_category(metadata: dict) -> tuple[Category | None, tuple[str, ...]]:
    """The category the registration states about itself, and the raw values it stated."""
    stated: list[str] = []
    for key in ("agent_type", "category"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            stated.append(value.strip())
    values = metadata.get("categories")
    if isinstance(values, (list, tuple)):
        stated.extend(
            item.strip() for item in values if isinstance(item, str) and item.strip()
        )
    found = {
        _DECLARED_CATEGORY_ALIASES[_normalise_declared(item)]
        for item in stated
        if _normalise_declared(item) in _DECLARED_CATEGORY_ALIASES
    }
    if len(found) == 1:
        return next(iter(found)), tuple(stated)
    return None, tuple(stated)


def classify(metadata: dict) -> tuple[Category | None, str, str]:
    """Which of the four jobs this registration describes, where that reading came from,
    and the exact reason — including when the answer is "no reading at all".

    Returns `(category | None, capability_source, rationale)`. A declaration in the
    registration wins over the rule table, because the operator saying what their own
    agent does outranks Docket reading their prose.

    Where the rule table has to decide, the whole decision is these three lines, and they
    are the rule rather than a heuristic layered on top of it:

      no category matched                       -> None
      one category matched                      -> that category
      several matched, one strictly ahead on
      the number of DISTINCT rules it matched   -> that category
      several matched, tied at the front        -> None

    The margin is counted in distinct rules, not in occurrences, so an agent that says
    "grid" nine times does not out-argue one that matches two lending rules once each.
    A tie assigns nothing, because an agent describing grid orders and lending health in
    equal measure is not evidence for either shelf. Every rationale names every category
    that matched and every rule that matched it, so a reader sees the losing side too.
    """
    declared, stated = declared_category(metadata)
    if declared is not None:
        return (
            declared,
            "registration_metadata",
            f"the registration declares {', '.join(stated)!r}",
        )
    text = capability_text(metadata)
    if not text.strip():
        return None, "docket_classified", "the registration carries no capability text"
    matches = _matched_terms(text)
    if not matches:
        return (
            None,
            "docket_classified",
            "no term in the category rule table appears in the capability text",
        )
    detail = "; ".join(
        f"{category.value}: {', '.join(terms)}"
        for category, terms in sorted(matches.items(), key=lambda item: item[0].value)
    )
    if len(matches) == 1:
        category = next(iter(matches))
        return (
            category,
            "docket_classified",
            f"the capability text matches only {category.value} rules ({detail})",
        )
    ranked = sorted(matches.items(), key=lambda item: (-len(item[1]), item[0].value))
    (leader, leader_terms), (runner_up, runner_up_terms) = ranked[0], ranked[1]
    if len(leader_terms) == len(runner_up_terms):
        return (
            None,
            "docket_classified",
            f"the capability text matches {len(matches)} categories with no rule-count "
            f"margin between the leaders ({detail}), so no category is assigned",
        )
    return (
        leader,
        "docket_classified",
        f"the capability text matches {len(matches)} categories and {leader.value} "
        f"matches the most rules ({len(leader_terms)} against "
        f"{len(runner_up_terms)} for {runner_up.value}): {detail}",
    )


def endpoints_from_metadata(metadata: dict) -> tuple[dict, ...]:
    """Every http(s) endpoint a registration names, as `{"kind", "url"}`, kind first.

    8004scan's agent detail publishes these under `services` keyed by protocol
    (`a2a`, `mcp`, `web`), which is where the kind comes from. The flat
    `a2a_endpoint`/`mcp_server`/`agent_url` fields older cards used are read too, so a
    card in either shape resolves.
    """
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, value: object) -> None:
        if not isinstance(value, str):
            return
        url = value.strip()
        if not url or not url.lower().startswith(("http://", "https://")):
            return
        key = (kind, url)
        if key not in seen:
            seen.add(key)
            found.append({"kind": kind, "url": url})

    for field_name, kind in (
        ("a2a_endpoint", "a2a"),
        ("mcp_server", "mcp"),
        ("agent_url", "web"),
    ):
        add(kind, metadata.get(field_name))
    services = metadata.get("services")
    if isinstance(services, dict):
        for key, service in services.items():
            kind = str(key).strip().lower() or "service"
            if isinstance(service, dict):
                add(kind, service.get("endpoint"))
            else:
                add(kind, service)
    elif isinstance(services, (list, tuple)):
        for service in services:
            if isinstance(service, dict):
                add(
                    str(service.get("protocol") or "service").strip().lower(),
                    service.get("endpoint"),
                )
    order = {kind: index for index, kind in enumerate(INVOCABLE_KINDS)}
    return tuple(
        sorted(
            found,
            key=lambda row: (
                order.get(row["kind"], len(order)),
                row["kind"],
                row["url"],
            ),
        )
    )


def unverified() -> dict:
    """The verification block of a listing nothing has been observed about yet."""
    return {"level": None, "evidence": [], "verified_at": None}


def payment_reading(verification: dict) -> tuple[bool, dict | None]:
    """Whether an x402 challenge was actually read from this agent, and the row saying so.

    Derived from the evidence on every serialisation rather than stored beside it, so the
    boolean cannot drift from the run that produced it and a hand-edited listing cannot
    assert a payment reading it has no evidence for.

    False covers two different situations and the row is what tells them apart: a row with
    `ok: false` means the endpoint was asked and answered without an x402 challenge; no row
    at all means the level was never attempted, because nothing has been verified yet.
    Both are published — a boolean alone would let "never asked" read as "asked and none".
    """
    for row in verification.get("evidence") or ():
        if isinstance(row, dict) and row.get("level") == "payment_tested":
            return bool(row.get("ok")), row
    return False, None


@dataclass(frozen=True)
class ExternalListing:
    """One third-party agent as Docket's marketplace shows it.

    `price` and `payment_method` are strings a provider supplied or `None`. Docket does
    not read a price off chain and does not invent one: a listing whose provider has not
    stated a price says so, rather than showing a zero that reads as free.
    """

    agent_id: str
    chain_id: int
    name: str
    owner: str | None
    registration_uri: str | None
    endpoints: tuple[dict, ...]
    declared_category: Category | None
    classified_category: Category | None
    capability_source: str
    price: str | None
    payment_method: str | None
    verification: dict
    hireable: bool
    capabilities: str = ""
    classification_rationale: str = ""
    sample_input: dict | None = None
    output_schema: dict | None = None
    source: Literal["registry_index", "provider_submitted"] = "registry_index"
    updated_at: str | None = None

    def __post_init__(self) -> None:
        if self.capability_source not in CAPABILITY_SOURCES:
            raise ValueError(
                f"{self.agent_id}: capability_source {self.capability_source!r} is not "
                f"one of {list(CAPABILITY_SOURCES)}"
            )
        level = self.verification.get("level")
        if level is not None and level not in LEVEL_ORDER:
            raise ValueError(
                f"{self.agent_id}: verification level {level!r} is not one of {list(LEVELS)}"
            )
        if self.hireable and not at_least(level, "docket_tested"):
            raise ValueError(
                f"{self.agent_id}: hireable requires level docket_tested or better, not "
                f"{level!r}. A listing nobody has run cannot be sold."
            )

    @property
    def category(self) -> Category | None:
        """The category shown, which is the declared one wherever there is one."""
        return self.declared_category or self.classified_category

    @property
    def level(self) -> str | None:
        return self.verification.get("level")

    @property
    def invocable_endpoints(self) -> tuple[dict, ...]:
        return tuple(row for row in self.endpoints if row["kind"] in INVOCABLE_KINDS)

    @property
    def payment_tested(self) -> bool:
        """Whether an x402 challenge was read from this agent. Never inferred from `level`.

        `docket_tested` hangs off `live`, not off `payment_tested`, so the level cannot be
        read as evidence about payment either way. This is the fact, on its own.
        """
        return payment_reading(self.verification)[0]

    def to_json(self) -> dict:
        category = self.category
        payment_tested, payment_evidence = payment_reading(self.verification)
        return {
            "agent_id": self.agent_id,
            "chain_id": self.chain_id,
            "name": self.name,
            "owner": self.owner,
            "registration_uri": self.registration_uri,
            "endpoints": [dict(row) for row in self.endpoints],
            "category": category.value if category is not None else None,
            "declared_category": (
                self.declared_category.value if self.declared_category else None
            ),
            "classified_category": (
                self.classified_category.value if self.classified_category else None
            ),
            "capability_source": self.capability_source,
            "capabilities": self.capabilities,
            "classification_rationale": self.classification_rationale,
            "price": self.price,
            "payment_method": self.payment_method,
            "sample_input": self.sample_input,
            "output_schema": self.output_schema,
            "verification": {
                "level": self.verification.get("level"),
                # Carried as its own boolean on every payload, never left to be inferred
                # from the level. `docket_tested` hangs off `live`, so a listing can be at
                # `docket_tested` with `payment_tested: false` — that is not a contradiction,
                # it is the two facts a level alone cannot say together.
                "payment_tested": payment_tested,
                "payment_tested_evidence": payment_evidence,
                "evidence": list(self.verification.get("evidence") or []),
                "verified_at": self.verification.get("verified_at"),
            },
            "hireable": self.hireable,
            "source": self.source,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_json(cls, payload: dict) -> "ExternalListing":
        def as_category(value):
            return Category(value) if value else None

        # The derived fields are dropped on the way in. `verification` on the object is
        # the observation — level, evidence, when — and `to_json` recomputes everything
        # read off it. Carrying them back would make a stored copy a second source for a
        # fact that has exactly one, and a hand-edited or forged value would survive the
        # round trip instead of being recomputed from the evidence.
        verification = {
            key: value
            for key, value in (payload.get("verification") or unverified()).items()
            if key not in ("payment_tested", "payment_tested_evidence")
        }

        return cls(
            agent_id=payload["agent_id"],
            chain_id=int(payload["chain_id"]),
            name=payload.get("name") or "",
            owner=payload.get("owner"),
            registration_uri=payload.get("registration_uri"),
            endpoints=tuple(dict(row) for row in payload.get("endpoints") or ()),
            declared_category=as_category(payload.get("declared_category")),
            classified_category=as_category(payload.get("classified_category")),
            capability_source=payload["capability_source"],
            price=payload.get("price"),
            payment_method=payload.get("payment_method"),
            verification=verification,
            hireable=bool(payload.get("hireable")),
            capabilities=payload.get("capabilities") or "",
            classification_rationale=payload.get("classification_rationale") or "",
            sample_input=payload.get("sample_input"),
            output_schema=payload.get("output_schema"),
            source=payload.get("source") or "registry_index",
            updated_at=payload.get("updated_at"),
        )


def at_least(level: str | None, floor: str) -> bool:
    """Whether a level reaches a floor. None reaches nothing."""
    if floor not in LEVEL_ORDER:
        raise ValueError(f"{floor!r} is not a verification level")
    if level is None:
        return False
    return LEVEL_ORDER.get(level, -1) >= LEVEL_ORDER[floor]


def listing_from_registry(
    detail: dict, *, chain_id: int = 56, updated_at: str | None = None
) -> ExternalListing:
    """Build a listing from one 8004scan agent card. Observes nothing: level stays None."""
    declared, _ = declared_category(detail)
    classified, source, rationale = classify(detail)
    owner = detail.get("owner_address")
    return ExternalListing(
        agent_id=str(detail.get("agent_id") or ""),
        chain_id=int(detail.get("chain_id") or chain_id),
        name=str(detail.get("name") or ""),
        owner=owner.lower() if isinstance(owner, str) and owner else None,
        registration_uri=detail.get("token_uri") or detail.get("registration_uri"),
        endpoints=endpoints_from_metadata(detail),
        declared_category=declared,
        classified_category=None if declared is not None else classified,
        capability_source=source,
        price=None,
        payment_method=None,
        verification=unverified(),
        hireable=False,
        capabilities=capability_text(detail),
        classification_rationale=rationale,
        source="registry_index",
        updated_at=updated_at,
    )


def load_seed(path) -> list[ExternalListing]:
    """Read a committed seed file into listings, refusing a level the file cannot justify."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [ExternalListing.from_json(row) for row in payload["listings"]]
