"""SSRF guard for probe targets.

Endpoint URLs come from a public on-chain registry that anyone can write to.
Before any probe we require an http(s) scheme and confirm that EVERY address the
host resolves to is publicly routable — a host resolving to both a public and a
private address is rejected, since we cannot control which one a later connect
would pick.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

SAFE = "ok"
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


def check_url(url: str, resolver=socket.getaddrinfo) -> tuple[bool, str]:
    try:
        parts = urlsplit(url or "")
    except ValueError:  # e.g. an unterminated IPv6 literal: http://[::1
        return False, "malformed url"
    if parts.scheme not in _ALLOWED_SCHEMES:
        return False, f"blocked scheme: {parts.scheme or '(none)'}"
    if not parts.hostname:
        return False, "no host in url"
    try:  # `.port` parses lazily, so it raises here rather than at urlsplit
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return False, "invalid port"
    try:
        infos = resolver(parts.hostname, port, 0, socket.SOCK_STREAM)
    except Exception as exc:  # DNS failure, bad host, anything
        return False, f"could not resolve host: {type(exc).__name__}"
    if not infos:
        return False, "could not resolve host: no records"
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False, f"unparseable address: {addr}"
        bad = _classify(ip)
        if bad:
            return False, bad
    return True, SAFE
