"""SSRF guard for probe targets.

Endpoint URLs come from a public on-chain registry that anyone can write to.
Before any probe we require an http(s) scheme and confirm that EVERY address the
host resolves to is publicly routable. The approved addresses are retained so
the probe can connect to one directly instead of resolving the hostname again.
"""

import ipaddress
import socket
import time
from urllib.parse import urlsplit

SAFE = "ok"
# A host we could not resolve is not a host we refused. Callers must be able to tell the two
# apart exactly — reporting a DNS failure as a policy block inflates the safety claim.
UNRESOLVED = "could not resolve host"
# Transient resolution failure is common enough that one miss must not become a published
# figure; a single retry after a pause separates a flake from a name that does not exist.
RESOLVE_RETRY_DELAY_S = 0.5
_ALLOWED_SCHEMES = {"http", "https"}
# RFC 6598 carrier-grade NAT. `ipaddress` reports this as neither private nor global, so it
# needs its own check: it routes to ISP and some cloud-internal infrastructure.
_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")


def _classify(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if ip.is_loopback:
        return "loopback address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_private:
        return "private address"
    # An IPv4-mapped IPv6 address (::ffff:100.64.0.1) is not `in` an IPv4 network — membership
    # is False across versions — so compare the mapped v4 address when there is one.
    if (getattr(ip, "ipv4_mapped", None) or ip) in _SHARED_ADDRESS_SPACE:
        return "shared address space"
    if ip.is_reserved:
        return "reserved address"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_unspecified:
        return "unspecified address"
    return None


def _resolve(hostname: str, port: int, resolver) -> list | None:
    """Resolve, retrying once after a pause. None means the host did not resolve."""
    for attempt in range(2):
        try:
            infos = resolver(hostname, port, 0, socket.SOCK_STREAM)
        except Exception:  # DNS failure, bad host, anything — reported as UNRESOLVED
            infos = None
        if infos:
            return list(infos)
        if attempt == 0:
            time.sleep(RESOLVE_RETRY_DELAY_S)
    return None


def check_address(address: str) -> tuple[bool, str]:
    """Classify one resolved or connected address against the probe policy."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False, f"unparseable address: {address}"
    bad = _classify(ip)
    if bad:
        return False, bad
    return True, SAFE


def check_url_addresses(
    url: str, resolver=socket.getaddrinfo
) -> tuple[bool, str, tuple[str, ...]]:
    """Vet a probe target and return the public addresses approved for the connection."""
    try:
        parts = urlsplit(url or "")
    except ValueError:  # e.g. an unterminated IPv6 literal: http://[::1
        return False, "malformed url", ()
    if parts.scheme not in _ALLOWED_SCHEMES:
        return False, f"blocked scheme: {parts.scheme or '(none)'}", ()
    if not parts.hostname:
        return False, "no host in url", ()
    try:  # `.port` parses lazily, so it raises here rather than at urlsplit
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return False, "invalid port", ()
    infos = _resolve(parts.hostname, port, resolver)
    if not infos:
        return False, UNRESOLVED, ()
    addresses = []
    for info in infos:
        addr = info[4][0]
        ok, reason = check_address(addr)
        if not ok:
            return False, reason, ()
        if addr not in addresses:
            addresses.append(addr)
    return True, SAFE, tuple(addresses)


def check_url(url: str, resolver=socket.getaddrinfo) -> tuple[bool, str]:
    """Vet a probe target. Only policy rejections are refusals; DNS failure is unresolved."""
    ok, reason, _ = check_url_addresses(url, resolver=resolver)
    return ok, reason
