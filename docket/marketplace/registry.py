"""The inventory: every service Docket runs, joined to its identity, its job and its record.

This is the current stock. Each of BNB's four categories has one service in it, and
two of the six services do work that is not one of those four jobs at all. Those two
are listed as themselves rather than pushed into a shelf they do not belong on.

Every figure here is derived from a recorded experiment under
`docket/advantage/experiments/` or a category read under
`docket/advantage/recorded_runs/`, and each one names the response fields it came from
in its own `method`. They are single observations, which is why every `window` says so:
one run, one wallet or source population, one payload. None of them is an average and
none of them is a claim about the next run.

The unflattering figures are here on purpose. warden-scan names one of the four hostile
vectors a manual read of the same text found; solvent-signal serves a read that sits
past the last on-chain anchor. A marketplace that published only the figures that
flatter its own stock would be publishing a verdict, which is the one thing Docket has
promised not to do.
"""

from ..advantage.record_run import load_record
from ..advantage.v2.report import run as v2_run, security_scores
from .models import CATEGORIES, Category, EvidenceRef, Metric, ServiceRecord

# The v2 security figures, scored here from the committed corpus and the committed run by the
# same functions /advantage/v2.json scores them with. A card that transcribed them would be a
# second copy of a number, and the copy that goes stale is whichever a reader happens to be
# looking at — so the card holds no security figure of its own, only this one, computed.
_SECURITY = security_scores()
_SECURITY_RUN = v2_run("03-security-corpus")
_WARDEN = _SECURITY["warden"]["decision_level"]
_KEYWORD = _SECURITY["keyword_match"]["decision_level"]
_EVERYTHING = _SECURITY["flag_everything"]["decision_level"]
_SECURITY_COUNTS = _SECURITY["warden"]["counts"]

_HEALTH_READ = load_record("health-guard")
_GRID_READ = load_record("grid-operator")
_YIELD_READ = load_record("yield-router")
_HEALTH_OUTPUT = _HEALTH_READ["agent_arm"]["output"]
_GRID_OUTPUT = _GRID_READ["agent_arm"]["output"]
_YIELD_OUTPUT = _YIELD_READ["agent_arm"]["output"]
_HEALTH_RESULT = _HEALTH_OUTPUT["result"]
_GRID_RESULT = _GRID_OUTPUT["result"]
_YIELD_RESULT = _YIELD_OUTPUT["result"]
_HEALTH_OBSERVATION = _HEALTH_OUTPUT["observation"]
_GRID_OBSERVATION = _GRID_OUTPUT["observation"]
_YIELD_OBSERVATION = _YIELD_OUTPUT["observation"]

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
    "health-guard": ServiceRecord(
        service_id="health-guard",
        category=Category.HEALTH_FACTOR,
        # The category whose own name is a figure Venus does not publish. That is stated in
        # the first breath of the limitations rather than worked around, because printing
        # an invented ratio under the label the shelf is named after is the exact
        # fabrication this inventory exists to refuse.
        agent_id=None,
        registration_uri=None,
        activation="one_shot",
        evidence_modality="live_read",
        metrics=(
            Metric(
                name="Entered markets carrying a borrow",
                unit="entered markets read",
                numerator=sum(
                    int(row["borrow_balance"]) > 0
                    for row in _HEALTH_RESULT["account"]["rows"]
                ),
                denominator=_HEALTH_RESULT["account"]["markets_entered"],
                window=_HEALTH_OBSERVATION["window"],
                observed_at=_HEALTH_OBSERVATION["observed_at"],
                method=_HEALTH_OBSERVATION["method"],
            ),
        ),
        evidence=(
            EvidenceRef(
                kind="advantage_task",
                url="/services/health-guard",
                label=(
                    "Task 05 — single recorded read summary; the full committed JSON is "
                    "docket/advantage/recorded_runs/05-health-guard-read.json and is not "
                    "exposed by a public artifact route in this build"
                ),
            ),
        ),
        limitations=(
            "Venus Core Pool on BSC and nothing else: no Isolated Pools, no other lending "
            "market, no other chain. Venus publishes no health factor — it publishes "
            "liquidity and shortfall in USD — so the collateral ratio in the report is "
            "derived here rather than read, and it carries its formula, its inputs and its "
            "scales inline; anybody looking for Aave's figure is looking for a number this "
            "protocol never produced. Only the markets getAssetsIn reports the account has "
            "entered are read, which is the same set the comptroller itself iterates, so a "
            "supply in a market the account never entered is not collateral and does not "
            "appear. Prices come from whichever oracle the comptroller currently names, "
            "read at the same block. What a hire returns is a preview and structurally only "
            "a preview: the object that produces it holds no session key, no signer and no "
            "submitter, it has no armed counterpart class in this build, and no execution "
            "path for a Venus call exists here — so acting on a drafted action needs work "
            "this stage did not do, on top of a session the wallet's owner grants on chain. "
            "Drafted actions are repay and supply-collateral only; borrowing and withdrawing "
            "are not encoded and no argument produces one. An action changes a balance Venus "
            "holds at the block it lands in and establishes nothing about a liquidation that "
            "did not happen, because that is a claim about a world nobody observed. A "
            "single recorded read; no paired run against a person stands behind the "
            "metrics on this card."
        ),
    ),
    "yield-router": ServiceRecord(
        service_id="yield-router",
        category=Category.YIELD_OPTIMISATION,
        # The other shelf that was bare. What fills it is a bounded claim rather than a
        # superlative: the comparison names the set it is a comparison within, and the set
        # names its source, its moment and everything it turned away.
        agent_id=None,
        registration_uri=None,
        activation="one_shot",
        evidence_modality="live_read",
        metrics=(
            Metric(
                name="Pools clearing the stated gate",
                unit="top-list pools considered",
                numerator=_YIELD_RESULT["universe"]["size"],
                denominator=_YIELD_RESULT["universe"]["considered"],
                window=_YIELD_OBSERVATION["window"],
                observed_at=_YIELD_OBSERVATION["observed_at"],
                method=_YIELD_OBSERVATION["method"],
            ),
        ),
        evidence=(
            EvidenceRef(
                kind="advantage_task",
                url="/services/yield-router",
                label=(
                    "Task 07 — single recorded read summary; the full committed JSON is "
                    "docket/advantage/recorded_runs/07-yield-router-read.json and is not "
                    "exposed by a public artifact route in this build"
                ),
            ),
        ),
        limitations=(
            "PancakeSwap v3 pools on BSC, read from PancakeSwap's own explorer snapshot, and "
            "nothing else: no other venue, no v2 pools, no farms, no lending. Every rate is "
            "a 24h observation annualised by 365 — one day, not a forecast — and it is a "
            "rate over the pool's TVL rather than over any position, so a concentrated "
            "position earns at it only while it is in range and earns nothing while it is "
            "not. Clearing the plausibility gate is not an endorsement: the gate rejects "
            "figures that cannot be true and says nothing about figures that merely should "
            "not be leaned on. Every claim is bounded by the stated eligible set, so highest "
            "here always means highest within that set at that moment and never highest "
            "anywhere. The switching cost is supplied by the caller and is not derived — "
            "Docket reads no BNB price here and does not invent one — and a break-even is "
            "only as good as the number it was handed. A move is drafted as one swap leg "
            "through the same PancakeSwap V2 router the grid uses; adding the resulting "
            "assets as liquidity to the destination pool is not built in this stage, so a "
            "drafted move gets the caller into the right asset and no further. Nothing is "
            "signed, approved, submitted or held and there is no execution guarantee of any "
            "kind: a drafted swap is a record of what acting would commit to, and acting "
            "needs a session the wallet's owner grants on chain. A single recorded read; "
            "no paired run against a person stands behind the metrics on this card."
        ),
    ),
    "grid-operator": ServiceRecord(
        service_id="grid-operator",
        category=Category.GRID_TRADING,
        # The shelf that was bare. It is stocked with the one thing Docket can actually
        # show — the whole mechanism, previewed against the chain — and the record below
        # says in its first breath that a hire previews rather than trades, because a
        # category filled with an overstatement is worse than one left honestly empty.
        agent_id=None,
        registration_uri=None,
        # `one_shot` and not `policy_action`, which is the tempting one. A hire runs once
        # and hands back a preview; it does not act on chain within a policy, and saying
        # it did would be claiming the half of this service that needs a session nobody
        # has granted yet.
        activation="one_shot",
        evidence_modality="live_read",
        metrics=(
            Metric(
                name="Levels quoted and hash-bound",
                unit="requested grid levels",
                numerator=sum(
                    bool(
                        level["intent"]
                        and level["simulation"]
                        and level["simulation"]["agrees"]
                    )
                    for level in _GRID_RESULT["levels"]
                ),
                denominator=_GRID_RESULT["plan"]["requested_levels"],
                window=_GRID_OBSERVATION["window"],
                observed_at=_GRID_OBSERVATION["observed_at"],
                method=_GRID_OBSERVATION["method"],
            ),
        ),
        evidence=(
            EvidenceRef(
                kind="advantage_task",
                url="/services/grid-operator",
                label=(
                    "Task 06 — single recorded read summary; the full committed JSON is "
                    "docket/advantage/recorded_runs/06-grid-preview-read.json and is not "
                    "exposed by a public artifact route in this build"
                ),
            ),
        ),
        limitations=(
            "PancakeSwap V2 exact-input swaps on BSC mainnet and nothing else: no V3, no "
            "limit orders, no adding or removing liquidity. What a hire returns is a "
            "preview and structurally only a preview — the object that produces it holds "
            "no session key, no signer and no submitter and has no method that sends a "
            "transaction, so it cannot move anything, and every figure in it is a read. "
            "Acting on a level needs a session the wallet's owner grants on chain, with a "
            "spend cap, a call allowlist and an expiry that the session validator enforces "
            "at validation time; Docket never holds the owner key and cannot grant or "
            "revoke on their behalf. Docket's own checks sit in front of the chain's and "
            "may only ever refuse more, never less. Each level's floor comes from a live "
            "router quote less the slippage the plan allows, and an action whose "
            "simulation disagrees with its own bounds is not submitted — but a level "
            "filling is a fill and not a gain. A confirmed transaction shows the action "
            "executed as it was authorised and shows nothing about whether it was worth "
            "taking. A single recorded read; no paired run against a person stands behind "
            "the metrics on this card. And the grid is deterministic rather than adaptive: it "
            "divides the band it was given, and it does not decide the band was wrong."
        ),
    ),
    "range-doctor": ServiceRecord(
        service_id="range-doctor",
        category=Category.REBALANCING,
        # No ERC-8004 identity has been registered for this one. Said rather than left
        # blank: an omitted field reads as an identity nobody printed.
        agent_id=None,
        registration_uri=None,
        activation="one_shot",
        evidence_modality="live_read",
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
        evidence_modality="historical",
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
        evidence_modality="live_read",
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
            # The one figure on this card that is not a transcription. It is computed at
            # import from the corpus and the run the v2 report serves, so this card and that
            # report cannot state two different numbers — and the null it is read against is
            # computed the same way and named in the same breath, because a detection rate
            # without one is a rate nobody can weigh.
            Metric(
                name="Labelled attacks flagged",
                unit="labelled attack payloads in the corpus",
                numerator=_WARDEN["recall"]["numerator"],
                denominator=_WARDEN["recall"]["denominator"],
                window=(
                    f"{_SECURITY_COUNTS['n_payloads']}-payload labelled corpus, three passes "
                    "each, one recorded run"
                ),
                observed_at=_SECURITY_RUN["finished_at"][:10],
                method=(
                    "advantage v2 experiment 03-security-corpus, decision level: payloads "
                    "labelled as attacks whose verdict was not ALLOW, computed from the "
                    "committed corpus and the committed run rather than transcribed. The "
                    f"stated keyword list flagged {_KEYWORD['recall']['numerator']} of the "
                    f"same {_KEYWORD['recall']['denominator']}, so the margin over it is "
                    f"{_WARDEN['recall']['numerator'] - _KEYWORD['recall']['numerator']} "
                    f"payloads; an arm that flags everything flags "
                    f"{_EVERYTHING['recall']['numerator']} of "
                    f"{_EVERYTHING['recall']['denominator']} and is right about "
                    f"{_EVERYTHING['precision']['numerator']} of "
                    f"{_EVERYTHING['precision']['denominator']}, which is the corpus base "
                    f"rate. This scan is right about {_WARDEN['precision']['numerator']} of "
                    f"{_WARDEN['precision']['denominator']}. "
                    f"{_SECURITY_COUNTS['n_failed_scans']} of the "
                    f"{_SECURITY_COUNTS['n_payloads'] * 3} scans failed and are counted as "
                    "failed trials rather than as misses"
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
            EvidenceRef(
                kind="advantage_task",
                url="/advantage/v2#03-security-corpus",
                label=(
                    "The v2 experiment — a labelled corpus scanned three times over, every "
                    "trial including the failures, and three null baselines computed beside it"
                ),
            ),
        ),
        limitations=(
            "Telemetry, not an enforcement boundary. Nothing here intercepts the text or "
            "stops it reaching anything, and what to do about a verdict stays with the "
            "caller. The hosted path is offered as-is with no availability or completeness "
            "promise, which is Warden's own documented position rather than a caveat "
            "Docket added. On the one payload v1 has a record for, it named one of the "
            "four hostile vectors a manual read found, and three of those four survive "
            "verbatim in the sanitized text it returned. That is one observation, not a "
            "pattern — and the run is published in full so a reader can weigh it. The v2 "
            "experiment is the repeated version of that question over a labelled corpus, "
            "and its figures are on this card with the nulls they are read against; both "
            "runs are published in full."
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
