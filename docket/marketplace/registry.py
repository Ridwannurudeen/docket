"""The inventory: every service Docket runs, joined to its identity, its job and its record.

This is the honest starting stock. One of BNB's four categories has a service in it;
three do not, and they say so rather than showing a card for something that does not
exist. Two of the three services do work that is not one of those four jobs at all,
and they are listed as themselves rather than pushed into a shelf they do not belong on.

Every figure here is transcribed from a recorded experiment under
`docket/advantage/experiments/`, and each one names the arm and field it came from in
its own `method`, so a reader can open /advantage and check it against the run. They
are single observations, which is why every `window` says so: one run, one wallet, one
payload. None of them is an average and none of them is a claim about the next run.

The unflattering figures are here on purpose. warden-scan names one of the four hostile
vectors a manual read of the same text found; solvent-signal serves a read that sits
past the last on-chain anchor. A marketplace that published only the figures that
flatter its own stock would be publishing a verdict, which is the one thing Docket has
promised not to do.
"""

from .models import CATEGORIES, Category, EvidenceRef, Metric, ServiceRecord

# Said wherever a category is shown. The ERC-8004 record carries nothing that states
# what job an agent does, so a category is a label Docket puts on its own work and
# never a property it measured on somebody else's.
CATEGORY_DECLARATION = (
    "A category here is Docket's own declaration about a service Docket runs: the job we "
    "say it does. It is not read from chain and it is not measured. An ERC-8004 "
    "registration records nothing about what job an agent does, so Docket declares "
    "categories for its own services and assigns none to a third-party registry agent."
)

# Said on a category with nothing in it. It states why the shelf is empty and stops
# there — no placeholder card, and no date nobody has committed to.
EMPTY_CATEGORY = (
    "No service here yet. Docket lists a service only where it runs the work itself and "
    "can show a recorded run behind it, and it has none for this job. It does not stock "
    "the shelf with agents from the registry, because nothing in an ERC-8004 record says "
    "what job an agent does — the registry is browsable in full under Research."
)

# Said above the services that are not in any of the four.
UNCATEGORISED_NOTE = (
    "These do work that is not one of the four jobs above. They are listed as themselves "
    "rather than filed under a category they do not belong to."
)

SERVICES: dict[str, ServiceRecord] = {
    "range-doctor": ServiceRecord(
        service_id="range-doctor",
        category=Category.REBALANCING,
        # No ERC-8004 identity has been registered for this one. Said rather than left
        # blank: an omitted field reads as an identity nobody printed.
        agent_id=None,
        registration_uri=None,
        activation="one_shot",
        metrics=(
            Metric(
                name="Position NFTs read",
                unit="position NFTs the wallet held",
                numerator=14,
                denominator=14,
                window="one recorded run against one wallet",
                observed_at="2026-08-08",
                method=(
                    "advantage task 01, agent arm: positions_examined against "
                    "positions_held, both carried in the result the hire returned"
                ),
            ),
            Metric(
                name="Positions counted but not detailed",
                unit="position NFTs read",
                numerator=13,
                denominator=14,
                window="the same recorded run",
                observed_at="2026-08-08",
                method=(
                    "advantage task 01, agent arm: closed_skipped against "
                    "positions_examined. Closed positions are counted and no detail is "
                    "returned for them, and there is no way to ask for it"
                ),
            ),
            Metric(
                name="Elapsed",
                unit="seconds",
                value=43.063,
                window="one recorded run, a single observation and not a mean",
                observed_at="2026-08-08",
                method=(
                    "advantage task 01, agent arm; the same question answered by hand in "
                    "the manual arm took 528.31 seconds"
                ),
            ),
        ),
        evidence=(
            EvidenceRef(
                kind="advantage_task",
                url="/advantage#01-liquidity",
                label=(
                    "Task 01 — the same wallet read by hiring and by hand, both outputs in "
                    "full with the hashes that bind them"
                ),
            ),
        ),
        limitations=(
            "PancakeSwap v3 on BSC only, and read-only: nothing is signed, approved or "
            "moved. It reads ticks rather than prices, and a position's uncollected fees "
            "come from tokensOwed, which is stale until something touches the position — "
            "so that figure can read low. One hire reads a bounded slice of a wallet's "
            "positions, newest first, and returns positions_held beside positions_examined "
            "so a truncated read announces itself. Closed positions are counted and not "
            "detailed. Every next step it states is conditional on a belief it names, and "
            "acting on any of them is the reader's decision."
        ),
    ),
    "solvent-signal": ServiceRecord(
        service_id="solvent-signal",
        # Not one of BNB's four jobs. Relaying a dated regime read is not rebalancing, a
        # grid, a yield move or a loan — and inventing a fifth category for it would be
        # describing a market rather than the one Docket was asked about.
        category=None,
        # The one identity Docket's own stock has on chain. Lowercased exactly as a
        # snapshot stores an agent_id, so /agents/{agent_id} can resolve it — though the
        # served snapshot was swept from agents with feedback and does not hold it.
        agent_id="56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:136384",
        registration_uri=None,
        activation="one_shot",
        metrics=(
            Metric(
                name="Receipts covered by the last on-chain anchor",
                unit="receipts in the chain",
                numerator=382,
                denominator=384,
                window="the receipt chain as SOLVENT served it on the recorded run",
                observed_at="2026-08-08",
                method=(
                    "advantage task 02, manual arm: anchored_count from the chain "
                    "recomputed from genesis, against the receipt_count the served payload "
                    "declares. The read Docket relays is receipt 383, past that anchor"
                ),
            ),
            Metric(
                name="Elapsed",
                unit="seconds",
                value=1.844,
                window="one recorded run, a single observation and not a mean",
                observed_at="2026-08-08",
                method=(
                    "advantage task 02, agent arm; the manual arm that actually established "
                    "the dating took 221.739 seconds, and the hire does not establish it"
                ),
            ),
        ),
        evidence=(
            EvidenceRef(
                kind="advantage_task",
                url="/advantage#02-trading",
                label=(
                    "Task 02 — what the provenance chain does and does not establish, with "
                    "the manual recomputation and the on-chain anchor in full"
                ),
            ),
        ),
        limitations=(
            "A historical record, not a live feed. SOLVENT completed its scored window on "
            "2026-06-28 and has published nothing since, so what arrives is dated "
            "2026-06-29 and will not change. It shows that a read existed at a position in "
            "a hash chain whose head is anchored on chain, which is what makes it "
            "impossible to back-date; it shows nothing about whether the call was right or "
            "whether anything happened next. The served read sits past the last anchor, so "
            "it is chain-consistent rather than anchor-covered, and recomputing the chain "
            "and reading the anchor on chain stays with the buyer. Docket relays the "
            "payload byte for byte and does not judge it."
        ),
    ),
    "warden-scan": ServiceRecord(
        service_id="warden-scan",
        # A security service, not one of the four. Filing it under one of them to fill a
        # shelf would be the exact fabrication this stage refuses.
        category=None,
        agent_id=None,
        registration_uri=None,
        activation="one_shot",
        metrics=(
            Metric(
                name="Hostile vectors named",
                unit="vectors a manual read of the same text found",
                numerator=1,
                denominator=4,
                window="one recorded payload, a single observation",
                observed_at="2026-08-08",
                method=(
                    "advantage task 03: the detections the hire returned, against the "
                    "vectors the manual arm found in the same bytes. Three of the four "
                    "survive verbatim in the sanitized text the hire handed back"
                ),
            ),
            Metric(
                name="Elapsed",
                unit="seconds",
                value=2.625,
                window="one recorded run, a single observation and not a mean",
                observed_at="2026-08-08",
                method=(
                    "advantage task 03, agent arm; the manual read that found four vectors "
                    "took 74.213 seconds"
                ),
            ),
        ),
        evidence=(
            EvidenceRef(
                kind="advantage_task",
                url="/advantage#03-security",
                label=(
                    "Task 03 — the recorded run this scan lost on substance, with the "
                    "payload and both readings in full"
                ),
            ),
        ),
        limitations=(
            "Telemetry, not an enforcement boundary. Nothing here intercepts the text or "
            "stops it reaching anything, and what to do about a verdict stays with the "
            "caller. The hosted path is offered as-is with no availability or completeness "
            "promise, which is Warden's own documented position rather than a caveat "
            "Docket added. On the one payload Docket has a record for, it named one of the "
            "four hostile vectors a manual read found, and three of those four survive "
            "verbatim in the sanitized text it returned. That is one observation, not a "
            "pattern — and the run is published in full so a reader can weigh it."
        ),
    ),
}


def get_record(service_id: str) -> ServiceRecord | None:
    return SERVICES.get(service_id)


def all_records() -> list[ServiceRecord]:
    """Every record, ordered by service id and by nothing else. An order that reordered
    itself would be a ranking, and Docket publishes none."""
    return [SERVICES[service_id] for service_id in sorted(SERVICES)]


def records_in(category: Category) -> list[ServiceRecord]:
    """The services Docket has declared into one category. Empty is a real answer here,
    and three of the four categories return it."""
    return [record for record in all_records() if record.category is category]


def category_counts() -> dict[Category, int]:
    """How many services stand in each of the four, in the declared category order."""
    return {entry.category: len(records_in(entry.category)) for entry in CATEGORIES}
