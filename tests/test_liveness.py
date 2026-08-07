import httpx

from docket import netguard
from docket.liveness import OUTCOMES, probe_snapshot
from docket.store import Store


def _seed(tmp_path, urls):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    store.upsert_endpoints(
        [{"agent_id": f"56:r:{i}", "kind": "a2a", "url": u} for i, u in enumerate(urls)], sid
    )
    return store, sid


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_outcome_vocabulary_is_closed():
    assert OUTCOMES == frozenset(
        {"responded", "timeout", "refused", "blocked", "unresolved", "error"}
    )


def test_responded_records_status_and_elapsed(tmp_path):
    store, sid = _seed(tmp_path, ["https://ok.example/a2a"])
    with _client(lambda r: httpx.Response(200, json={"ok": True})) as c:
        result = probe_snapshot(store, sid, client=c, resolver=_public)
    assert result["responded"] == 1
    row = next(iter(store.iter_liveness(sid)))
    assert row["outcome"] == "responded" and row["status_code"] == 200
    assert row["elapsed_ms"] is not None and row["observed_at"]


def test_non_2xx_still_counts_as_responded(tmp_path):
    """A 404 proves the host is up; it is an observation, not a judgement."""
    store, sid = _seed(tmp_path, ["https://ok.example/a2a"])
    with _client(lambda r: httpx.Response(404)) as c:
        probe_snapshot(store, sid, client=c, resolver=_public)
    row = next(iter(store.iter_liveness(sid)))
    assert row["outcome"] == "responded" and row["status_code"] == 404


def test_ssrf_blocked_target_is_never_connected(tmp_path):
    store, sid = _seed(tmp_path, ["http://127.0.0.1:8080/admin"])
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200)

    with _client(handler) as c:
        result = probe_snapshot(store, sid, client=c, resolver=_loopback)
    assert calls["n"] == 0  # the guard ran before any request
    assert result["blocked"] == 1
    row = next(iter(store.iter_liveness(sid)))
    assert row["outcome"] == "blocked" and "loopback" in (row["detail"] or "")


def test_timeout_and_refused_are_distinguished(tmp_path):
    store, sid = _seed(tmp_path, ["https://a.example/1", "https://b.example/2"])

    def handler(request):
        if request.url.host == "a.example":
            raise httpx.ReadTimeout("too slow", request=request)
        raise httpx.ConnectError("refused", request=request)

    with _client(handler) as c:
        probe_snapshot(store, sid, client=c, resolver=_public)
    outcomes = {r["outcome"] for r in store.iter_liveness(sid)}
    assert outcomes == {"timeout", "refused"}


def test_a_host_that_will_not_resolve_is_unresolved_not_blocked(tmp_path, monkeypatch):
    """DNS failing is our problem, not a refusal we made. On the first real run this was
    8 points of the headline and 16 of 50 'blocked' hosts resolved fine on retry."""
    monkeypatch.setattr(netguard, "RESOLVE_RETRY_DELAY_S", 0)
    store, sid = _seed(tmp_path, ["https://gone.example/a2a"])
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200)

    with _client(handler) as c:
        result = probe_snapshot(store, sid, client=c, resolver=_boom)
    assert calls["n"] == 0  # still never connected to
    assert result["unresolved"] == 1
    assert result["blocked"] == 0
    row = next(iter(store.iter_liveness(sid)))
    assert row["outcome"] == "unresolved"


def test_a_loopback_target_is_still_blocked(tmp_path):
    """Real agents publish this exact URL. `blocked` must keep meaning 'refused on policy'."""
    store, sid = _seed(tmp_path, ["http://localhost:9001/.well-known/agent-card.json"])
    with _client(lambda r: httpx.Response(200)) as c:
        result = probe_snapshot(store, sid, client=c, resolver=_loopback)
    assert result["blocked"] == 1
    assert result["unresolved"] == 0


def test_resolution_is_retried_once_before_declaring_unresolved(tmp_path, monkeypatch):
    monkeypatch.setattr(netguard, "RESOLVE_RETRY_DELAY_S", 0)
    store, sid = _seed(tmp_path, ["https://flaky.example/a2a"])
    attempts = {"n": 0}

    def flaky(host, port, *a, **kw):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise OSError("getaddrinfo failed")
        return _public(host, port)

    with _client(lambda r: httpx.Response(200)) as c:
        result = probe_snapshot(store, sid, client=c, resolver=flaky)
    assert attempts["n"] == 2  # the flake was retried, not published
    assert result["unresolved"] == 0
    assert result["responded"] == 1


def _public(host, port, *a, **kw):
    return [(2, 1, 6, "", ("93.184.216.34", port or 443))]


def _loopback(host, port, *a, **kw):
    return [(2, 1, 6, "", ("127.0.0.1", port or 80))]


def _boom(host, port, *a, **kw):
    raise OSError("getaddrinfo failed")
