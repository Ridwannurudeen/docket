"""Probe published endpoints and record what was observed — nothing more.

Nobody in this ecosystem currently knows which registered agents actually answer.
One GET each settles it, but the URLs come from a registry anyone can write to,
so every target is vetted by the SSRF guard first. The connection uses the
approved address directly and its peer is checked before any response metadata
is recorded. Redirects are deliberately not followed: the guard vetted the URL
we were given, not wherever a 302 would send us next.

`responded` means a response arrived at any status — a 404 still proves the host
is up. None of these outcomes is a verdict about the agent behind the URL.
"""

import ipaddress
import socket
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from .netguard import UNRESOLVED, check_address, check_url_addresses
from .store import Store

# `blocked` means one thing only: we refused this target on policy grounds. A host that would
# not resolve is `unresolved` — filing it as blocked would credit the guard with a refusal it
# never made, and on the first real run that was 8 points of the headline figure.
OUTCOMES = frozenset(
    {"responded", "timeout", "refused", "blocked", "unresolved", "error"}
)
TIMEOUT_S = 8.0
HEADERS = {
    "user-agent": "Docket/0.1 (+https://github.com/Ridwannurudeen/docket)",
    "accept": "application/json",
}
# One hit per host per second: many agents publish under a single domain, and a sweep
# must not look like a burst to whoever operates it.
MIN_HOST_INTERVAL_S = 1.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pace(last_hit: dict[str, float], url: str) -> None:
    """Hold each host to one hit a second, however many agents publish under it."""
    try:
        host = urlsplit(url).hostname
    except ValueError:  # malformed; the guard rejects it without connecting
        return
    if not host:
        return
    previous = last_hit.get(host)
    if previous is not None:
        gap = time.monotonic() - previous
        if gap < MIN_HOST_INTERVAL_S:
            time.sleep(MIN_HOST_INTERVAL_S - gap)
    last_hit[host] = time.monotonic()


def _peer_policy_reason(response: httpx.Response, approved_address: str) -> str | None:
    stream = response.extensions.get("network_stream")
    if stream is None:
        return "connected peer address unavailable"
    try:
        server = stream.get_extra_info("server_addr")
    except (AttributeError, OSError):
        return "connected peer address unavailable"
    if not isinstance(server, (tuple, list)) or not server:
        return "connected peer address unavailable"
    peer_address = str(server[0])
    ok, reason = check_address(peer_address)
    if not ok:
        return f"connected peer is a {reason}"
    if ipaddress.ip_address(peer_address) != ipaddress.ip_address(approved_address):
        return "connected peer differs from approved address"
    return None


def probe_one(
    client: httpx.Client, endpoint: dict, *, now: str, resolver=socket.getaddrinfo
) -> dict:
    """One attempt at one endpoint. No request is ever retried — these are third-party hosts,
    not our own. Only name resolution gets a second try, before any connection is opened."""
    url = endpoint["url"]
    observation = {
        "snapshot_id": endpoint["snapshot_id"],
        "agent_id": endpoint["agent_id"],
        "url": url,
        "observed_at": now,
        "status_code": None,
        "elapsed_ms": None,
        "detail": None,
    }
    ok, reason, addresses = check_url_addresses(url, resolver=resolver)
    if not ok:
        outcome = "unresolved" if reason == UNRESOLVED else "blocked"
        return {**observation, "outcome": outcome, "detail": reason}

    started = time.monotonic()
    try:
        # follow_redirects=False is load-bearing: an allowed public host that 302s to
        # 169.254.169.254 would otherwise walk straight past the guard.
        original_url = httpx.URL(url)
        approved_address = addresses[0]
        headers = {
            **HEADERS,
            "host": original_url.netloc.decode("ascii"),
            "connection": "close",
        }
        extensions = {"sni_hostname": original_url.raw_host.decode("ascii")}
        pinned_url = original_url.copy_with(host=approved_address)
        with client.stream(
            "GET",
            pinned_url,
            headers=headers,
            timeout=TIMEOUT_S,
            follow_redirects=False,
            extensions=extensions,
        ) as resp:
            peer_reason = _peer_policy_reason(resp, approved_address)
            if peer_reason:
                return {**observation, "outcome": "blocked", "detail": peer_reason}
            observation.update(outcome="responded", status_code=resp.status_code)
    except httpx.TimeoutException as exc:
        observation.update(outcome="timeout", detail=type(exc).__name__)
    except httpx.ConnectError as exc:
        observation.update(outcome="refused", detail=type(exc).__name__)
    except (
        Exception
    ) as exc:  # a registry-supplied URL can break httpx outside HTTPError
        observation.update(outcome="error", detail=type(exc).__name__)
    observation["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return observation


def probe_snapshot(
    store: Store,
    snapshot_id: int,
    *,
    client: httpx.Client | None = None,
    limit: int | None = None,
    kinds: tuple[str, ...] = ("a2a", "mcp"),
    resolver=socket.getaddrinfo,
) -> dict:
    """Probe every endpoint of the given kinds in a snapshot and store the observations."""
    # Drained before any network call: a suspended generator holds its sqlite connection open
    # for the whole sweep (Phase 1a).
    targets: list[dict] = []
    for kind in kinds:
        targets.extend(store.iter_endpoints(snapshot_id, kind=kind))
    if limit is not None:
        targets = targets[:limit]

    last_hit: dict[str, float] = {}
    rows = []
    for endpoint in targets:
        _pace(last_hit, endpoint["url"])
        if client is None:
            # A fresh direct client per target prevents a connection pinned for one hostname
            # from being pooled for another hostname that happens to share its address.
            with httpx.Client(trust_env=False) as owned_client:
                rows.append(
                    probe_one(owned_client, endpoint, now=_now(), resolver=resolver)
                )
        else:
            rows.append(probe_one(client, endpoint, now=_now(), resolver=resolver))

    store.record_liveness(rows)
    outcomes = [row["outcome"] for row in rows]
    return {
        "probed": len(rows),
        "responded": outcomes.count("responded"),
        "blocked": outcomes.count("blocked"),
        "unresolved": outcomes.count("unresolved"),
        "failed": sum(
            1 for outcome in outcomes if outcome in ("timeout", "refused", "error")
        ),
    }
