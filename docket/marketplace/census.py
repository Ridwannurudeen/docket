"""Find candidate BSC agents for the four categories and verify every one of them.

This is the runner behind `docs/marketplace/verification-*.md` and the committed seed
file the API loads into an empty table. It is read-only in every direction: it searches
the registry index, reads `ownerOf` from BSC, and makes at most two guarded requests per
agent. It never presents a payment, never sends a transaction, and never calls a tool a
server lists.

The candidate set is not hand-picked. Each category contributes its own queries, printed
below, and a candidate qualifies when the rule table classifies it into that category
from its own registration text. Three agents are additionally named because the pivot
plan names them, and they are verified whatever their classification says — including
when the answer is that they classify into nothing, which is a finding rather than a
reason to drop them.

Run it as:

    python -m docket.marketplace.census --out docs/marketplace --seed docket/marketplace/seed

Every figure the document publishes is a count this script wrote: candidates found,
candidates with an invocable endpoint, agents probed, agents live, agents docket_tested.
"""

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ..scan8004 import Scan8004Client
from .external import listing_from_registry
from .models import Category
from .verification import apply_result, verify_listing

# The queries each category asks the registry, verbatim. `search` matches whole tokens in
# an agent's name, description and owner address; it is not a prefix match, which is why
# the phrases here are the ones an operator would actually write.
CATEGORY_QUERIES: dict[Category, tuple[str, ...]] = {
    Category.REBALANCING: (
        "rebalancing",
        "concentrated liquidity",
        "liquidity position",
        "LP range",
    ),
    Category.GRID_TRADING: ("grid",),
    Category.YIELD_OPTIMISATION: (
        "yield optimisation",
        "yield router",
        "APY",
        "supply rate",
    ),
    Category.HEALTH_FACTOR: (
        "health factor",
        "liquidation",
        "lending position",
    ),
}

# Named by the pivot plan. Verified whether or not the rule table files them anywhere.
NAMED_CANDIDATES = ("43129", "171927", "6441")

# How many classified candidates each category contributes, newest token id first. A cap
# rather than everything: this makes real requests to other people's hosts, and a census
# that swept every match would be a load test wearing a survey's clothes.
CANDIDATES_PER_CATEGORY = 6
SEARCH_PAGE = 50
# One agent a second. `liveness` holds itself to one hit per host per second for the same
# reason: many agents publish under one domain and a survey must not look like a burst.
PACE_S = 1.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_candidates(
    client: Scan8004Client,
    *,
    chain_id: int = 56,
    per_category: int = CANDIDATES_PER_CATEGORY,
) -> dict:
    """Search, classify, and return the agent cards worth verifying.

    Returns `{"details": {token_id: card}, "queries": [...], "counts": {...}}`. Cards are
    fetched only for candidates that declare A2A or MCP in the list response, because the
    list response does not carry endpoints and a card costs a request each.
    """
    # The unfiltered total, read once so every count below has the population it is a
    # fraction of. A LOWER BOUND on the chain, in the sense `store.registry_total`
    # documents: it is what the index answered at one moment, and the registry grows.
    _, registry_total = client.search_agents(chain_id, limit=1, offset=0)
    queries: list[dict] = []
    seen: dict[str, dict] = {}
    for category, terms in CATEGORY_QUERIES.items():
        for term in terms:
            rows, total = client.search_agents(
                chain_id, query=term, limit=SEARCH_PAGE, offset=0
            )
            queries.append(
                {
                    "category": category.value,
                    "query": term,
                    "total": total,
                    "returned": len(rows),
                }
            )
            for row in rows:
                token = str(row.get("token_id") or "")
                if token and token not in seen:
                    seen[token] = row

    declares_endpoint = {
        token: row
        for token, row in seen.items()
        if {str(p).upper() for p in (row.get("supported_protocols") or [])}
        & {"A2A", "MCP"}
    }

    chosen: dict[str, dict] = {}
    per_category_counts: Counter = Counter()
    for token in sorted(declares_endpoint, key=int, reverse=True):
        row = declares_endpoint[token]
        listing = listing_from_registry(row, chain_id=chain_id)
        category = listing.category
        if category is None:
            continue
        if per_category_counts[category.value] >= per_category:
            continue
        per_category_counts[category.value] += 1
        chosen[token] = row
    selected_by_classification = sorted(chosen, key=int, reverse=True)
    # Counted before the named ids are folded in, and the overlap is named rather than
    # buried: two of the three the plan names were already selected on their own text,
    # and adding 3 to 24 to get 27 would publish one agent twice.
    added_because_named = [token for token in NAMED_CANDIDATES if token not in chosen]
    for token in added_because_named:
        chosen[token] = seen.get(token) or {"token_id": token}

    details = {}
    for token in sorted(chosen, key=int, reverse=True):
        details[token] = client.get_agent(chain_id, token)
    return {
        "details": details,
        "queries": queries,
        "counts": {
            "registry_total_when_the_pass_ran": registry_total,
            "matched_by_search": len(seen),
            "declaring_a2a_or_mcp": len(declares_endpoint),
            "selected_by_classification": len(selected_by_classification),
            "named_by_the_plan": len(NAMED_CANDIDATES),
            "added_because_named": added_because_named,
            "verified": len(details),
            "selected_per_category": dict(per_category_counts),
        },
    }


def run_census(*, chain_id: int = 56, pace_s: float = PACE_S) -> dict:
    """Collect, verify, and return everything the document and the seed are built from."""
    started = _now()
    with Scan8004Client() as client:
        collected = collect_candidates(client, chain_id=chain_id)

    listings = []
    results = []
    for token, detail in collected["details"].items():
        listing = listing_from_registry(detail, chain_id=chain_id)
        if not listing.agent_id:
            results.append(
                {
                    "token_id": token,
                    "agent_id": None,
                    "skipped": "the registry index holds no card for this token id",
                }
            )
            continue
        result = verify_listing(listing)
        verified = apply_result(listing, result)
        listings.append(verified.to_json())
        results.append(
            {
                "token_id": token,
                "agent_id": verified.agent_id,
                "name": verified.name,
                "category": verified.category.value if verified.category else None,
                "capability_source": verified.capability_source,
                # What the registration CLAIMS about payment, recorded beside what the
                # endpoint actually did. The two disagree often enough that publishing
                # either alone would mislead.
                "x402_declared": bool(detail.get("x402_supported")),
                "classification_rationale": verified.classification_rationale,
                "endpoints": [dict(row) for row in verified.endpoints],
                "level": result.level,
                "chain_read_failed": result.outage,
                "evidence": result.evidence,
            }
        )
        time.sleep(pace_s)

    by_level = Counter(row.get("level") or "unverified" for row in results)
    by_category = Counter(row.get("category") or "unclassified" for row in results)
    # `live` follows the sweep's vocabulary and a 404 reaches it, so the narrower count is
    # published beside it. A survey that reported only the level would read as 26 working
    # endpoints when a third of them answer that the declared path is not there.
    answered_2xx = sum(
        1
        for row in results
        for evidence in row.get("evidence", ())
        if evidence["level"] == "live" and evidence["detail"].get("answered_2xx")
    )
    return {
        "generated_at": started,
        "finished_at": _now(),
        "chain_id": chain_id,
        "method": {
            "registry": "8004scan /api/v1/agents, search= narrowed, 0.4 s pacing",
            "ownership": "IdentityRegistry.ownerOf and tokenURI over public BSC RPCs",
            "endpoint": (
                "one guarded GET per declared a2a/mcp endpoint, plus at most one sample "
                "invocation; no payment presented and no transaction sent"
            ),
            "queries": collected["queries"],
            "candidates_per_category": CANDIDATES_PER_CATEGORY,
            "named_candidates": list(NAMED_CANDIDATES),
        },
        "counts": {
            **collected["counts"],
            "by_level": dict(by_level),
            "by_category": dict(by_category),
            "live_answering_2xx": answered_2xx,
            "declaring_x402_support": sum(
                1 for row in results if row.get("x402_declared")
            ),
        },
        "results": results,
        "listings": listings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", required=True, help="directory for the census evidence"
    )
    parser.add_argument("--seed", required=True, help="directory for the seed listings")
    parser.add_argument("--chain-id", type=int, default=56)
    args = parser.parse_args(argv)

    census = run_census(chain_id=args.chain_id)
    date = census["generated_at"][:10]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    # newline="\n" on both writes: `.gitattributes` forces LF on every text file in this
    # repository because Docket hashes what it publishes, and a census written with CRLF
    # on Windows would differ from the same census written on the deployment host.
    (out / f"census-{date}.json").write_text(
        json.dumps(census, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    seed_dir = Path(args.seed)
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / f"external-listings-{date}.json").write_text(
        json.dumps(
            {
                "generated_at": census["generated_at"],
                "method": census["method"],
                "listings": census["listings"],
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(census["counts"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
