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


def _latest_observations(store: Store, snapshot_id: int) -> list[dict]:
    """One row per endpoint: the most recent probe of it. `liveness` is append-only history,
    so counting raw rows would count a re-probed endpoint twice and inflate the total."""
    latest: dict[tuple[str, str], dict] = {}
    for row in store.iter_liveness(snapshot_id):  # ordered by id, so the last write wins
        latest[(row["agent_id"], row["url"])] = row
    return list(latest.values())


def coverage_report(store: Store, snapshot_id: int) -> dict:
    meta = store.snapshot(snapshot_id)
    sampled = store.agent_count(snapshot_id)
    expected = int(meta.get("expected") or 0)
    counts = Counter()
    publishers = Counter()
    for agent in store.iter_agents(snapshot_id):
        sig = signals_for(agent)
        publishers[sig["publisher"]] += 1
        for key in ("placeholder_name", "callable", "has_feedback", "describes_itself", "x402"):
            if sig[key]:
                counts[key] += 1

    def pct(n: int) -> float:
        return round(100.0 * n / sampled, 3) if sampled else 0.0

    endpoint_kinds = Counter(e["kind"] for e in store.iter_endpoints(snapshot_id))
    observations = _latest_observations(store, snapshot_id)
    probed = len(observations)
    responded = [o for o in observations if o["outcome"] == "responded"]
    stamps = sorted(o["observed_at"] for o in observations)

    return {
        "snapshot_id": snapshot_id,
        "chain_id": int(meta.get("chain_id") or 0),
        "captured_at": meta.get("finished_at") or meta.get("started_at"),
        "sampled": sampled,
        "expected": expected,
        "dropped": max(expected - sampled, 0),
        "complete": expected == sampled and sampled > 0,
        "with_feedback": counts["has_feedback"],
        "with_feedback_pct": pct(counts["has_feedback"]),
        "callable": counts["callable"],
        "callable_pct": pct(counts["callable"]),
        "placeholder_name": counts["placeholder_name"],
        "describes_itself": counts["describes_itself"],
        "x402": counts["x402"],
        "distinct_publishers": len(publishers),
        "top_publishers": [
            {"publisher": p, "count": n, "share_pct": pct(n)} for p, n in publishers.most_common(5)
        ],
        "endpoints_resolved": sum(endpoint_kinds.values()),
        "endpoints_probeable": sum(endpoint_kinds[k] for k in _PROBE_KINDS),
        "endpoints_probed": probed,
        "endpoints_responded": len(responded),
        # Share of the endpoints actually probed. Dividing by `sampled` would restate a probe
        # result as a claim about the whole registry — the flattering lie available here.
        "responded_pct": round(100.0 * len(responded) / probed, 3) if probed else 0.0,
        "blocked": sum(1 for o in observations if o["outcome"] == "blocked"),
        "failed": sum(1 for o in observations if o["outcome"] in _FAILURE_OUTCOMES),
        "agents_probed": len({o["agent_id"] for o in observations}),
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
        "| Signal | Agents | Share |",
        "| --- | ---: | ---: |",
        f"| Has at least one feedback record | {report['with_feedback']:,} | {report['with_feedback_pct']}% |",
        f"| Declares a callable endpoint (A2A or MCP) | {report['callable']:,} | {report['callable_pct']}% |",
        f"| Supports x402 | {report['x402']:,} | |",
        f"| Auto-generated placeholder name | {report['placeholder_name']:,} | |",
        f"| Distinct publishers | {report['distinct_publishers']:,} | |",
        "",
        "## Largest publishers",
        "",
        "| Publisher | Agents | Share of snapshot |",
        "| --- | ---: | ---: |",
    ]
    for row in report["top_publishers"]:
        lines.append(f"| {row['publisher']} | {row['count']:,} | {row['share_pct']}% |")
    lines += ["", "## Endpoint liveness", ""]
    if report["endpoints_probed"]:
        window = report["liveness_observed_at"]
        lines += [
            f"Enrichment resolved **{report['endpoints_resolved']:,}** endpoint URLs from agent "
            f"cards, of which **{report['endpoints_probeable']:,}** are A2A or MCP. "
            f"**{report['endpoints_probed']:,}** were probed between {window['first']} and "
            f"{window['last']}.",
            "",
            "Method: one GET per endpoint, single attempt, 8s timeout, no redirects followed, "
            "every target vetted by an SSRF guard before any connection is opened.",
            "",
            "| Observation | Endpoints |",
            "| --- | ---: |",
            f"| Responded — an HTTP response arrived, any status | "
            f"{report['endpoints_responded']:,} |",
            f"| No response — timed out, refused, or errored | {report['failed']:,} |",
            f"| Blocked by the SSRF guard — never contacted | {report['blocked']:,} |",
            "",
            f"**{report['responded_pct']}%** of probed endpoints responded, covering "
            f"**{report['agents_responded']:,}** of the **{report['agents_probed']:,}** agents "
            f"probed. That share is of the endpoints probed — not of the "
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
