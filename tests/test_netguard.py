from docket.netguard import SAFE, check_url


def _resolver(ip: str):
    """Stub getaddrinfo returning one A record for the given IP."""

    def resolve(host, port, *a, **kw):
        return [(2, 1, 6, "", (ip, port or 443))]

    return resolve


def _echo(host, port, *a, **kw):
    """Stub getaddrinfo echoing the host back as its own address.

    Address-based tests must not use a fixed public stub: that would return a public IP no
    matter which host was checked, so the assertion would pass even if the guard were gutted.
    """
    return [(2, 1, 6, "", (host, port or 443))]


def test_public_https_is_allowed():
    ok, reason = check_url("https://agent.example.com/a2a", resolver=_resolver("93.184.216.34"))
    assert ok is True and reason == SAFE


def test_loopback_is_blocked():
    ok, reason = check_url("http://localhost:8080/admin", resolver=_resolver("127.0.0.1"))
    assert ok is False and "loopback" in reason


def test_private_range_is_blocked():
    for ip in ("10.0.0.5", "192.168.1.10", "172.16.0.1"):
        ok, reason = check_url("http://internal/x", resolver=_resolver(ip))
        assert ok is False and "private" in reason


def test_cloud_metadata_address_is_blocked():
    ok, reason = check_url(
        "http://169.254.169.254/latest/meta-data/", resolver=_resolver("169.254.169.254")
    )
    assert ok is False and "link-local" in reason


def test_non_http_schemes_are_blocked():
    for url in ("file:///etc/passwd", "ftp://x/y", "gopher://x", "ws://x/y"):
        ok, reason = check_url(url, resolver=_resolver("93.184.216.34"))
        assert ok is False and "scheme" in reason


def test_unresolvable_host_is_blocked_not_crashed():
    def boom(*a, **kw):
        raise OSError("getaddrinfo failed")

    ok, reason = check_url("https://nope.invalid/x", resolver=boom)
    assert ok is False and "resolve" in reason


def test_missing_host_is_blocked():
    ok, reason = check_url("https:///nohost", resolver=_resolver("93.184.216.34"))
    assert ok is False and "host" in reason


def test_all_resolved_ips_must_be_public():
    """A host resolving to both a public and a private IP is rejected."""

    def dual(host, port, *a, **kw):
        return [(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]

    ok, reason = check_url("https://sneaky.example/x", resolver=dual)
    assert ok is False


def test_malformed_port_is_blocked_not_raised():
    """A registry URL is attacker-controlled; a bad port must block, never crash the prober."""
    for url in ("http://example.com:99999/x", "http://example.com:abc/x"):
        ok, reason = check_url(url, resolver=_echo)
        assert ok is False and "port" in reason


def test_malformed_url_is_blocked_not_raised():
    """urlsplit itself raises on an unterminated IPv6 literal, before any port access."""
    ok, reason = check_url("http://[::1", resolver=_echo)
    assert ok is False and "malformed" in reason


def test_shared_address_space_is_blocked():
    """RFC 6598 CGNAT: `ipaddress` calls it neither private nor global, so it needs its own check."""
    ok, reason = check_url("http://100.64.0.1/x", resolver=_echo)
    assert ok is False and "shared address space" in reason


def test_ipv4_mapped_ipv6_addresses_stay_blocked():
    """Regression guard on _classify: the mapped forms are easy to reopen when editing it."""
    for host, expected in (
        ("[::ffff:127.0.0.1]", "loopback"),
        ("[::ffff:10.0.0.5]", "private"),
        ("[::ffff:100.64.0.1]", "shared address space"),
    ):
        ok, reason = check_url(f"http://{host}/x", resolver=_echo)
        assert ok is False and expected in reason
