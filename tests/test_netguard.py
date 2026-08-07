from docket.netguard import SAFE, check_url


def _resolver(ip: str):
    """Stub getaddrinfo returning one A record for the given IP."""

    def resolve(host, port, *a, **kw):
        return [(2, 1, 6, "", (ip, port or 443))]

    return resolve


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
