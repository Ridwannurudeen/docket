"""Generated coverage numbers for one snapshot.

Every figure Docket publishes about the BSC registry comes from here, computed
from stored rows. Nothing is typed into prose by hand, and a snapshot that did
not capture everything the API claimed says so in its own output.
"""

from collections import Counter

from .signals import signals_for
from .store import Store


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
    lines += [
        "",
        "These are factual observations about registry metadata. None of them asserts "
        "that an agent is safe, trustworthy, or fit for a given purpose.",
    ]
    return "\n".join(lines)
