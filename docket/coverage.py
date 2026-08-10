"""Generated coverage numbers for one snapshot.

Every figure Docket publishes about the BSC registry comes from here, computed
from stored rows. Nothing is typed into prose by hand, and a snapshot that did
not capture everything the API claimed says so in its own output.
"""

from collections import Counter

from .signals import signals_for
from .store import Store

# What liveness.probe_snapshot targets by default. The other resolved kinds (web, service)
# are recorded but never probed, so a probe count must not be read against all of them.
_PROBE_KINDS = ("a2a", "mcp")
_FAILURE_OUTCOMES = ("timeout", "refused", "error")
# Outcomes that can only have been reached by issuing an HTTP request. `blocked` and
# `unresolved` are the two that cannot: one is a refusal Docket made before opening a
# connection, the other a hostname that never resolved, and neither target was ever sent
# anything. A response rate over them divides answers by endpoints nobody asked.
_ATTEMPTED_OUTCOMES = ("responded", *_FAILURE_OUTCOMES)


def _latest_observations(store: Store, snapshot_id: int) -> list[dict]:
    """One row per endpoint: the most recent probe of it. `liveness` is append-only history,
    so counting raw rows would count a re-probed endpoint twice and inflate the total."""
    latest: dict[tuple[str, str], dict] = {}
    for row in store.iter_liveness(snapshot_id):  # ordered by id, so the last write wins
        latest[(row["agent_id"], row["url"])] = row
    return list(latest.values())


def coverage_report(store: Store, snapshot_id: int) -> dict:
    meta = store.snapshot(snapshot_id)
    chain_id = int(meta.get("chain_id") or 0)
    sampled = store.agent_count(snapshot_id)
    expected = int(meta.get("expected") or 0)
    counts = Counter()
    families = Counter()
    for agent in store.iter_agents(snapshot_id):
        sig = signals_for(agent)
        families[sig["name_family"]] += 1
        for key in ("placeholder_name", "callable", "has_feedback", "describes_itself", "x402"):
            if sig[key]:
                counts[key] += 1

    def pct(n: int) -> float:
        return round(100.0 * n / sampled, 3) if sampled else 0.0

    endpoint_kinds = Counter(e["kind"] for e in store.iter_endpoints(snapshot_id))
    observations = _latest_observations(store, snapshot_id)
    attempted = [o for o in observations if o["outcome"] in _ATTEMPTED_OUTCOMES]
    responded = [o for o in observations if o["outcome"] == "responded"]
    stamps = sorted(o["observed_at"] for o in observations)

    return {
        "snapshot_id": snapshot_id,
        "chain_id": chain_id,
        "captured_at": meta.get("finished_at") or meta.get("started_at"),
        "sampled": sampled,
        "expected": expected,
        "dropped": max(expected - sampled, 0),
        # Complete against `expected`, which is the total for the query `population` names —
        # never against the registry. The two must be read together or the first overstates.
        "complete": expected == sampled and sampled > 0,
        "population": meta.get("population"),
        # The scale `complete` is silent about. A snapshot swept from a filtered query is
        # complete the moment it reaches the end of that query, which says nothing about how
        # much of the chain the query left out.
        "registry_total": store.registry_total(chain_id),
        "with_feedback": counts["has_feedback"],
        "with_feedback_pct": pct(counts["has_feedback"]),
        "callable": counts["callable"],
        "callable_pct": pct(counts["callable"]),
        "placeholder_name": counts["placeholder_name"],
        "describes_itself": counts["describes_itself"],
        "x402": counts["x402"],
        # Grouped by the first token of a self-declared name, not by minter. `signals.name_family`
        # carries the whole caveat; the field is named for what it measures so a reader of the
        # number alone cannot mistake it for provenance read off chain.
        "distinct_name_families": len(families),
        "top_name_families": [
            {"name_family": f, "count": n, "share_pct": pct(n)} for f, n in families.most_common(5)
        ],
        "endpoints_resolved": sum(endpoint_kinds.values()),
        "endpoints_probeable": sum(endpoint_kinds[k] for k in _PROBE_KINDS),
        # Two counts, because they answer two different questions and one number cannot.
        # `evaluated` is every endpoint liveness considered; `attempted` is the subset an
        # HTTP request was actually issued to.
        "endpoints_evaluated": len(observations),
        "endpoints_attempted": len(attempted),
        "endpoints_responded": len(responded),
        # Both rates published, each named for its own denominator. The share of attempted
        # says how often an endpoint Docket sent a request to answered; the share of
        # evaluated says how much
        # of the declared surface answered at all. Publishing only one of them under a name
        # that promises the other is the failure this pair replaces.
        "responded_pct_of_attempted": (
            round(100.0 * len(responded) / len(attempted), 3) if attempted else 0.0
        ),
        "responded_pct_of_evaluated": (
            round(100.0 * len(responded) / len(observations), 3) if observations else 0.0
        ),
        # Kept apart deliberately: `blocked` is a refusal we made, `unresolved` is a name that
        # would not resolve. Summing them would publish DNS trouble as a safety statistic.
        "blocked": sum(1 for o in observations if o["outcome"] == "blocked"),
        "unresolved": sum(1 for o in observations if o["outcome"] == "unresolved"),
        "failed": sum(1 for o in observations if o["outcome"] in _FAILURE_OUTCOMES),
        "agents_attempted": len({o["agent_id"] for o in attempted}),
        "agents_responded": len({o["agent_id"] for o in responded}),
        "liveness_observed_at": {"first": stamps[0], "last": stamps[-1]} if stamps else None,
    }


def render_markdown(report: dict) -> str:
    status = "complete" if report["complete"] else "partial"
    lines = [
        f"# BSC agent registry — snapshot {report['snapshot_id']} ({status})",
        "",
        f"Captured {report['captured_at']} from chain {report['chain_id']}.",
        f"Stored **{report['sampled']:,}** of **{report['expected']:,}** agents the API "
        f"reported (`dropped={report['dropped']:,}`).",
        "",
        f"Population swept: **{report['population'] or 'unspecified'}**. Both figures above "
        f"are totals for that query, not for the registry — the largest chain-wide total any "
        f"sweep here has recorded is "
        f"**{f'{report['registry_total']:,}' if report['registry_total'] else 'unmeasured'}**.",
        "",
        "| Signal | Agents | Share |",
        "| --- | ---: | ---: |",
        f"| Has at least one feedback record | {report['with_feedback']:,} | {report['with_feedback_pct']}% |",
        f"| Declares a callable endpoint (A2A or MCP) | {report['callable']:,} | {report['callable_pct']}% |",
        f"| Supports x402 | {report['x402']:,} | |",
        f"| Auto-generated placeholder name | {report['placeholder_name']:,} | |",
        f"| Distinct name families | {report['distinct_name_families']:,} | |",
        "",
        "## Largest name families",
        "",
        "Grouped by the first token of the name each agent declared, or by owner where the "
        "registry generated the name. This is a name heuristic, not verified minter "
        "provenance — two unrelated owners choosing the same first word share a row.",
        "",
        "| Name family | Agents | Share of snapshot |",
        "| --- | ---: | ---: |",
    ]
    for row in report["top_name_families"]:
        lines.append(f"| {row['name_family']} | {row['count']:,} | {row['share_pct']}% |")
    lines += ["", "## Endpoint liveness", ""]
    if report["endpoints_evaluated"]:
        window = report["liveness_observed_at"]
        lines += [
            f"Enrichment resolved **{report['endpoints_resolved']:,}** endpoint URLs from agent "
            f"cards, of which **{report['endpoints_probeable']:,}** are A2A or MCP. "
            f"**{report['endpoints_evaluated']:,}** were evaluated between {window['first']} and "
            f"{window['last']}, and **{report['endpoints_attempted']:,}** of those had a request "
            f"issued — the rest were refused by the guard or would not resolve, so nothing was "
            f"ever sent to them.",
            "",
            "Method: one GET per endpoint, single attempt, 8s timeout, no redirects followed, "
            "every target vetted by an SSRF guard before any connection is opened, and a host "
            "that fails to resolve retried once before being counted as unresolved.",
            "",
            "| Observation | Endpoints |",
            "| --- | ---: |",
            f"| Responded — an HTTP response arrived, any status | "
            f"{report['endpoints_responded']:,} |",
            f"| No response — timed out, refused, or errored | {report['failed']:,} |",
            f"| Blocked by the SSRF guard — never contacted | {report['blocked']:,} |",
            f"| Unresolved — the host did not resolve, so nothing was probed | "
            f"{report['unresolved']:,} |",
            "",
            f"**{report['responded_pct_of_attempted']}%** of the "
            f"**{report['endpoints_attempted']:,}** endpoints a request was issued to "
            f"responded, and "
            f"**{report['responded_pct_of_evaluated']}%** of all "
            f"**{report['endpoints_evaluated']:,}** evaluated did. Those responses cover "
            f"**{report['agents_responded']:,}** of the **{report['agents_attempted']:,}** agents "
            f"a request was issued for. Both shares are of endpoints — not of the "
            f"{report['sampled']:,} agents in this snapshot.",
            "",
            "A response means a host answered. It is not evidence that the agent behind the URL "
            "does anything useful.",
        ]
    else:
        lines.append("No endpoints have been probed for this snapshot.")
    lines += [
        "",
        "These are factual observations about registry metadata and observed endpoint "
        "behaviour. None of them asserts that an agent is safe, trustworthy, or fit for a "
        "given purpose.",
    ]
    return "\n".join(lines)
