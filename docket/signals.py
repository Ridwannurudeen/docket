"""Deterministic, factual signals over a stored agent row. No network, no verdicts.

Each signal answers an observable question about registry data. None of them
claims an agent is safe or trustworthy — Docket surfaces evidence and lets a
reader judge. Every function here is pure so it can be unit-tested and re-run
over an old snapshot without touching the API.
"""

import re

# Auto-generated names 8004scan assigns when an agent publishes no metadata.
_PLACEHOLDER = re.compile(r"^agent\s*#?\d+$", re.IGNORECASE)
# Callable in practice: something can actually invoke it agent-to-agent.
_CALLABLE_PROTOCOLS = {"A2A", "MCP"}
# Name families registered in bulk under near-identical names; collapsed so one of them
# cannot dominate a listing page. Verified on BSC 2026-08-06/07.
_FAMILY_PREFIXES = ("ave.ai", "purr-fect", "termix", "quack", "q402", "mevx")


def _clean_name(agent: dict) -> str:
    return (agent.get("name") or "").strip()


def is_placeholder_name(agent: dict) -> bool:
    return bool(_PLACEHOLDER.match(_clean_name(agent)))


def name_family(agent: dict) -> str:
    """Group agents by the first token of the name they chose (or by owner where the registry
    generated the name). This is a heuristic over a self-declared string and is NOT verified
    minter provenance: nothing here reads who deployed or minted anything, and two unrelated
    owners who pick the same first word share a key.
    """
    name = _clean_name(agent).lower()
    if not name or _PLACEHOLDER.match(name):
        owner = (agent.get("owner_address") or "").lower()
        return f"owner:{owner}" if owner else "unknown"
    for prefix in _FAMILY_PREFIXES:
        if name.startswith(prefix):
            return prefix
    return name.split()[0]


def signals_for(agent: dict) -> dict:
    protocols = {p.upper() for p in (agent.get("supported_protocols") or [])}
    description = (agent.get("description") or "").strip()
    return {
        "placeholder_name": is_placeholder_name(agent),
        "callable": bool(protocols & _CALLABLE_PROTOCOLS),
        "has_feedback": int(agent.get("total_feedbacks") or 0) > 0,
        "describes_itself": bool(description),
        "x402": bool(agent.get("x402_supported")),
        "name_family": name_family(agent),
    }
