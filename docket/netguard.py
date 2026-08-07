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


def _classify(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    if ip.is_loopback:
        return "loopback address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_private:
        return "private address"
    if ip.is_reserved:
        return "reserved address"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_unspecified:
        return "unspecified address"
    return None


def check_url(url: str, resolver=socket.getaddrinfo) -> tuple[bool, str]:
    parts = urlsplit(url or "")
    if parts.scheme not in _ALLOWED_SCHEMES:
        return False, f"blocked scheme: {parts.scheme or '(none)'}"
    if not parts.hostname:
        return False, "no host in url"
    port = parts.port or (443 if parts.scheme == "https" else 80)
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
