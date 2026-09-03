"""What this deployment is running, and whether the things it depends on answered.

Two surfaces over one function. `GET /api/status` serves the document; `GET /status` renders
the same document as a page. Neither computes anything the other does not: a page that
disagreed with the JSON behind it would be a second source of truth for the one question this
module exists to answer.

Three deliberate refusals:

  * No figure is published without the observation it came from and the tolerance it is
    judged against. "degraded" on its own tells an operator to look somewhere; the row that
    is out of tolerance tells them where.
  * `down` is reserved for the database. Every other reading here is read out of it, so a
    store that cannot be read is not a deployment with four unknown readings — it is a
    deployment whose own record of itself is gone.
  * A canary that has never run, or that recorded `not_yet_exercised`, is not a failure. Its
    paid limbs are configuration-gated and its timer is deliberately disabled between
    exercises, so counting silence as a fault would leave this page permanently degraded and
    therefore permanently unread. A recorded `failed` verdict is counted.

Both routes are public, and one of the readings is an outbound chain read, so neither may be
taken per request. The report is built at most once per `REPORT_TTL_S` per process and served
from that reading until it expires — carrying the instant it was taken, so a reader sees the
staleness rather than being told a cached document is current. The chain read behind it is one
attempt against one endpoint: `escrow/chain.py::Rpc` fails over because a job that cannot read
the chain cannot proceed, whereas a status reading that cannot read the chain has read
something true and should say so in one connection rather than eight. `/api/status` also
carries the same per-peer allowance the rest of this application's free work does, so the
cache cannot be the only thing standing between a caller and this deployment's RPC budget.
"""

import html
import sqlite3
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from ..escrow import constants as escrow_constants
from ..store import PROBE_WINDOW_HOURS, Store

WEB_DIR = Path(__file__).resolve().parent / "web"
STATUS_CONTENT_MARKER = "<!-- status-content -->"

# One connection, once per window, so the worst case a person waits is the timeout itself.
RPC_TIMEOUT_S = 5
RPC_ENDPOINT = escrow_constants.RPC_URLS[0]
# How long one reading stands. Long enough that a poll cannot drive the chain read, short
# enough that an operator watching a deploy is never more than a minute behind it.
REPORT_TTL_S = 60
# Sixty reads an hour per peer: sixty times what a human refresh needs and ten times what the
# probe timer spends, so the bound is only ever reached by something that is not reading it.
STATUS_ALLOWANCE = 60
STATUS_WINDOW_S = 3600
MAX_ALLOWANCE_CLIENTS = 10_000
# `docket-refresh.timer` fires every six hours. Two scheduled windows is the boundary between
# a run that has not landed yet and a refresh that is not running, and the second is the one
# an operator has to act on.
REFRESH_MAX_AGE_SECONDS = 12 * 3600
REFRESH_INTERVAL_SECONDS = 6 * 3600
# `docket-refresh.service` carries TimeoutStartSec=2h, so a sweep still running past that is
# one systemd has killed or is about to. Below it, a sweep in flight is a sweep working.
REFRESH_SWEEP_TIMEOUT_S = 2 * 3600
DB_TIMEOUT_S = 5
GIT_TIMEOUT_S = 5
# The verdict that means the canary ran and something it checked was wrong. `not_yet_exercised`
# describes a canary that reached no limb, which is a configuration state rather than a fault.
CANARY_FAILED_VERDICT = "failed"
CANARY_RUNNING_VERDICT = "running"
# The verdicts that mean the paid path was actually put through its paces.
EXERCISED_CANARY_VERDICTS = frozenset({"passed", "failed"})
# `docket-canary.service` carries TimeoutStartSec=8min; a `running` row older than that is a
# run whose result nobody will ever receive.
CANARY_RUN_TIMEOUT_S = 8 * 60
# How many of the newest probe runs decide the verdict. The window counts stay at 24 hours;
# one transient failure should not hold the page red for the rest of the day.
PROBE_VERDICT_RUNS = 3


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _age_seconds(stamp: str | None, now: datetime) -> int | None:
    if not stamp:
        return None
    try:
        observed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return max(int((now - observed).total_seconds()), 0)


def default_release_commit_path() -> Path:
    """`deploy/release.sh` writes the release commit at the root of the environment it
    publishes, and the application runs out of that environment, so `sys.prefix` names it
    whether the process was started through `/opt/docket/.venv` or through the versioned
    directory that symlink points at. A source checkout has no such file, which is the
    condition the git fallback below exists for."""
    return Path(sys.prefix) / "RELEASE-commit.txt"


def deployed_commit(release_commit_path: Path | str) -> str:
    """The commit this process is running, named by the strongest available evidence.

    A released environment records it; a checkout can be asked; anything else says `source`
    rather than guessing, because a wrong commit on a status page is worse than no commit.
    """
    try:
        recorded = Path(release_commit_path).read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        recorded = ""
    if recorded:
        return recorded
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "source"
    head = completed.stdout.strip()
    return head if completed.returncode == 0 and head else "source"


def _redacted(path: Path) -> str:
    """The database file and the directory holding it, and nothing above them. The production
    path is published in the deployment runbook, so this is not concealment; it keeps a
    developer's home directory off a public page."""
    return "/".join(path.parts[-2:]) if len(path.parts) >= 2 else path.name


def _journal_mode(path: Path) -> str | None:
    """Read through a read-only URI connection so a status request never creates a database
    and never rewrites the mode it is reporting on."""
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=DB_TIMEOUT_S)
    except sqlite3.Error:
        return None
    try:
        return str(conn.execute("PRAGMA journal_mode").fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _latest_refresh(store: Store, now: datetime) -> dict:
    """The newest sweep a reader is actually served.

    `latest_complete_snapshot_id` and not `latest_snapshot_id`: a refresh takes up to two
    hours, and for every minute of it the newest row has a null `finished_at`. Judging that
    row would paint the page degraded for the whole of a sweep that is working — a status
    surface that goes red while the thing it watches succeeds is one an operator learns to
    ignore. The sweep in flight is reported separately, below, where it can be judged on the
    only thing wrong with it: taking too long.
    """
    snapshot_id = store.latest_complete_snapshot_id()
    row = store.snapshot(snapshot_id) if snapshot_id is not None else {}
    at = row.get("finished_at")
    return {
        "at": at,
        "age_seconds": _age_seconds(at, now),
        "complete": snapshot_id is not None,
    }


def _refresh_in_progress(store: Store, now: datetime) -> dict | None:
    """The sweep that has begun and not finished, when there is one newer than the served
    snapshot. `None` is the ordinary state between runs, not an absence of information."""
    newest = store.latest_snapshot_id()
    if newest is None or newest == store.latest_complete_snapshot_id():
        return None
    row = store.snapshot(newest)
    if row.get("finished_at"):
        # Finished and not promotable: a page-bounded or non-advancing sweep. It is not in
        # flight, and `latest_refresh` already reports the older snapshot still being served.
        return None
    started_at = row.get("started_at")
    return {"started_at": started_at, "age_seconds": _age_seconds(started_at, now)}


def _latest_canary(store: Store, service_id: str, now: datetime) -> dict:
    """`exercised` says whether the paid path was ever actually put through its paces, which
    neither the verdict nor the timestamp says on its own: `not_yet_exercised` is a recorded
    run that exercised nothing, and it reads like a result."""
    run = store.latest_canary_run(service_id)
    verdict = run.get("verdict")
    finished_at = run.get("finished_at")
    started_at = run.get("started_at")
    at = finished_at or started_at
    return {
        "verdict": verdict,
        "exercised": verdict in EXERCISED_CANARY_VERDICTS,
        "finished_at": finished_at,
        "age_seconds": _age_seconds(at, now),
    }


def _probes(store: Store, now: datetime) -> dict:
    """Two figures with two jobs. `ok_count`/`fail_count` describe the whole window, which is
    what a reader wants to know. The verdict is taken from the last few runs only: one
    transient failure is not a reason to show a red page for the next twenty-four hours, and
    a run of them is."""
    runs = store.latest_probe_runs(PROBE_WINDOW_HOURS, now=now)
    recent = runs[:PROBE_VERDICT_RUNS]
    return {
        "last_run_at": runs[0]["started_at"] if runs else None,
        "ok_count": sum(1 for run in runs if run["ok"]),
        "fail_count": sum(1 for run in runs if not run["ok"]),
        "window_hours": PROBE_WINDOW_HOURS,
        "recent_ok": sum(1 for run in recent if run["ok"]),
        "recent_considered": len(recent),
    }


def _session(url: str) -> Web3:
    # `exception_retry_configuration=None` is the whole of "one attempt". web3 7.16.0's
    # HTTPProvider defaults to retrying ConnectionError, HTTPError and Timeout five times
    # with an exponential backoff, and `eth_blockNumber` is on its retry allowlist — so the
    # timeout below bounds one connection while the provider quietly makes five. Measured
    # against a socket that accepts and never answers: 5 connections and 5 x timeout plus
    # 1.875s of backoff, which at RPC_TIMEOUT_S=5 is ~27s inside a lock this application
    # holds while it builds a reading.
    w3 = Web3(
        Web3.HTTPProvider(
            url,
            request_kwargs={"timeout": RPC_TIMEOUT_S},
            exception_retry_configuration=None,
        )
    )
    # BSC is PoA: 280-byte extraData, which a block read rejects without this.
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def bounded_rpc_probe() -> dict:
    """One `eth_blockNumber`, one endpoint, one attempt, capped at RPC_TIMEOUT_S.

    No failover, deliberately. `escrow/chain.py::Rpc` walks four endpoints twice each because
    a job that cannot read the chain cannot proceed; here a chain that did not answer is the
    reading, and eight outbound connections would make a public route into a way to spend this
    deployment's RPC budget. `reason` names what happened instead, so `ok: false` is a finding
    an operator can act on rather than a bare flag.
    """
    started = time.monotonic()
    try:
        block_number = int(_session(RPC_ENDPOINT).eth.block_number)
        reason = None
    # A socket, a proxy, a throttle or a malformed response can arrive as anything, and none
    # of them is this process being wrong.
    except Exception as exc:
        block_number = None
        reason = f"{type(exc).__name__}: {exc}"[:200]
    return {
        "endpoint_host": urlsplit(RPC_ENDPOINT).hostname,
        "ok": block_number is not None,
        "block_number": block_number,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "reason": reason,
    }


class _ReportCache:
    """One reading per window per process, taken under a lock.

    The lock is held across the build rather than around a double check, deliberately: a
    lock-free cache lets every concurrent first request miss together and make the outbound
    read this cache exists to bound. Waiting behind one reading in flight is the cheaper
    failure, and FastAPI runs these routes on its threadpool, so nothing else is blocked.

    The document it hands back carries the `generated_at` of the reading, not of the request,
    so a caller can see how stale the answer is instead of being told it is current.
    """

    def __init__(self, build, *, ttl_s: int = REPORT_TTL_S, clock=time.monotonic) -> None:
        self._build = build
        self._ttl_s = ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._report: dict | None = None
        self._taken_at = 0.0

    def __call__(self) -> dict:
        with self._lock:
            now = self._clock()
            if self._report is None or now - self._taken_at >= self._ttl_s:
                self._report = self._build()
                self._taken_at = now
            return self._report


def spend_window(
    windows: OrderedDict[str, tuple[float, int]],
    client_ip: str,
    *,
    attempts: int,
    window_seconds: int,
    clock=time.monotonic,
) -> int | None:
    """Take one attempt from a peer's window, or return the seconds until it resets.

    The same shape `create_app` uses for free hires and on-demand probes, and keyed the same
    way: on the peer address only. `X-Forwarded-For` is caller-controlled, and reading it here
    would turn the bound into a header anyone can rewrite.
    """
    now = clock()
    while windows:
        _, (oldest_started, _) = next(iter(windows.items()))
        if now - oldest_started < window_seconds:
            break
        windows.popitem(last=False)
    current = windows.get(client_ip)
    if current is None:
        if len(windows) >= MAX_ALLOWANCE_CLIENTS:
            windows.popitem(last=False)
        started, used = now, 0
        windows[client_ip] = (started, used)
    else:
        started, used = current
    if used >= attempts:
        return int(window_seconds - (now - started)) + 1
    windows[client_ip] = (started, used + 1)
    return None


def refresh_out_of_tolerance(refresh: dict) -> bool:
    age = refresh["age_seconds"]
    return not refresh["complete"] or age is None or age > REFRESH_MAX_AGE_SECONDS


def sweep_out_of_tolerance(in_progress: dict | None) -> bool:
    """A sweep in flight is fine until it outlives the deadline systemd would kill it at."""
    if in_progress is None:
        return False
    age = in_progress["age_seconds"]
    return age is None or age > REFRESH_SWEEP_TIMEOUT_S


def canary_out_of_tolerance(canary: dict) -> bool:
    """A recorded failure is a fault, and so is a run that started and never reported: the
    unit is killed at its own timeout, so a `running` row older than that is a canary whose
    result nobody will ever get."""
    if canary["verdict"] == CANARY_FAILED_VERDICT:
        return True
    if canary["verdict"] != CANARY_RUNNING_VERDICT:
        return False
    age = canary["age_seconds"]
    return age is None or age > CANARY_RUN_TIMEOUT_S


def probes_out_of_tolerance(probes: dict) -> bool:
    considered = probes["recent_considered"]
    return considered > 0 and probes["recent_ok"] < considered


def status_report(
    store: Store,
    *,
    release_commit_path: Path | str,
    now: datetime,
    rpc_probe,
    canary_service_id: str = "range-doctor",
    commit: str | None = None,
) -> dict:
    """`commit` is the already-resolved deployment identity. `router` resolves it once, at
    process start, and passes it here: `RELEASE-commit.txt` is reached through `sys.prefix`,
    a release flips the symlink under that path, and a process that outlived the flip would
    otherwise read the incoming release's commit and report it as the code it is running."""
    reachable = True
    try:
        refresh = _latest_refresh(store, now)
        in_progress = _refresh_in_progress(store, now)
        canary = _latest_canary(store, canary_service_id, now)
        probes = _probes(store, now)
    # The store refuses a database whose journal mode is not DELETE with a RuntimeError, and
    # a deleted or corrupt file arrives as sqlite3.Error. Both are the same fact for a reader:
    # this deployment cannot read its own record.
    except (sqlite3.Error, RuntimeError, OSError):
        reachable = False
        refresh = {"at": None, "age_seconds": None, "complete": False}
        in_progress = None
        canary = {
            "verdict": None,
            "exercised": False,
            "finished_at": None,
            "age_seconds": None,
        }
        probes = {
            "last_run_at": None,
            "ok_count": 0,
            "fail_count": 0,
            "window_hours": PROBE_WINDOW_HOURS,
            "recent_ok": 0,
            "recent_considered": 0,
        }
    rpc = rpc_probe()

    if not reachable:
        status = "down"
    elif (
        refresh_out_of_tolerance(refresh)
        or sweep_out_of_tolerance(in_progress)
        or canary_out_of_tolerance(canary)
        or not rpc["ok"]
        or probes_out_of_tolerance(probes)
    ):
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "deployed_commit": (
            commit if commit is not None else deployed_commit(release_commit_path)
        ),
        "db": {
            "reachable": reachable,
            "journal_mode": _journal_mode(Path(store.path)),
            "path_redacted": _redacted(Path(store.path)),
        },
        "latest_refresh": refresh,
        "refresh_in_progress": in_progress,
        "latest_canary": canary,
        "rpc": rpc,
        "probes": probes,
        "generated_at": now.isoformat(),
    }


def _esc(value) -> str:
    return html.escape(str(value))


def _display(value) -> str:
    return "not recorded" if value in (None, "") else _esc(value)


def _canary_state(canary: dict) -> str:
    """What the canary row means, rather than what it stores. `not_yet_exercised` is a
    recorded run that reached no limb, and printed raw it reads like a result."""
    verdict = canary["verdict"]
    if not canary["exercised"]:
        return "not exercised" if verdict != CANARY_RUNNING_VERDICT else "unfinished"
    return _display(verdict)


def _canary_exercised_at(canary: dict) -> str:
    if not canary["exercised"] or not canary["finished_at"]:
        return "never"
    return _esc(canary["finished_at"])


def _aged(label: str, age: int | None) -> str:
    """A reading with no observation behind it has no age either, and appending one anyway
    is how "not recorded, not recorded old" reaches a page."""
    return label if age is None else f"{label}, {age:,}s old"


def status_page(shell: str, report: dict) -> str:
    """Render the served document. Every row states the reading, the observation it was taken
    from, and the tolerance it is judged against, so a reader can check the verdict rather
    than take it."""
    refresh = report["latest_refresh"]
    in_progress = report["refresh_in_progress"]
    canary = report["latest_canary"]
    rpc = report["rpc"]
    probes = report["probes"]
    database = report["db"]
    runs = probes["ok_count"] + probes["fail_count"]

    rows = (
        (
            "Snapshot refresh",
            _aged(
                "complete" if refresh["complete"] else "none served",
                refresh["age_seconds"],
            ),
            _display(refresh["at"]),
            f"a complete sweep under {REFRESH_MAX_AGE_SECONDS:,}s old "
            f"(two {REFRESH_INTERVAL_SECONDS:,}s refresh windows)",
            refresh_out_of_tolerance(refresh),
        ),
        (
            "Sweep in flight",
            (
                "none running"
                if in_progress is None
                else _aged("running", in_progress["age_seconds"])
            ),
            _display(None if in_progress is None else in_progress["started_at"]),
            f"none, or one under {REFRESH_SWEEP_TIMEOUT_S:,}s old — the deadline systemd "
            "starts the refresh with. A sweep in flight is not a missing sweep",
            sweep_out_of_tolerance(in_progress),
        ),
        (
            "Service canary",
            _aged(_canary_state(canary), canary["age_seconds"]),
            _display(canary["finished_at"]),
            f"not {CANARY_FAILED_VERDICT}, and not left unfinished for more than "
            f"{CANARY_RUN_TIMEOUT_S:,}s. A canary that has not exercised the paid path is "
            "not counted against this deployment",
            canary_out_of_tolerance(canary),
        ),
        (
            "BSC read",
            (
                f"block {rpc['block_number']:,} in {rpc['latency_ms']:,}ms"
                if rpc["ok"]
                else f"no answer in {rpc['latency_ms']:,}ms — {_esc(rpc['reason'])}"
            ),
            _display(rpc["endpoint_host"]),
            f"one eth_blockNumber against {_esc(urlsplit(RPC_ENDPOINT).hostname)}, "
            f"one connection, no retry, {RPC_TIMEOUT_S}s",
            not rpc["ok"],
        ),
        (
            "Synthetic probes",
            f"{probes['ok_count']} of {runs} runs passed in {probes['window_hours']}h; "
            f"{probes['recent_ok']} of the last {probes['recent_considered']} passed",
            _display(probes["last_run_at"]),
            f"the last {PROBE_VERDICT_RUNS} runs all passed. The {probes['window_hours']}h "
            "counts are reported but not judged: one transient failure is not a day-long "
            "fault",
            probes_out_of_tolerance(probes),
        ),
    )
    reading_rows = "".join(
        f'<tr><th scope="row">{_esc(name)}</th>'
        f'<td>{value}</td><td class="mono">{observed}</td>'
        f'<td class="dim">{_esc(tolerance)}</td>'
        f"<td>{'out of tolerance' if breached else 'within tolerance'}</td></tr>"
        for name, value, observed, tolerance, breached in rows
    )
    identity_rows = "".join(
        f'<tr><th scope="row">{_esc(label)}</th><td class="mono">{value}</td></tr>'
        for label, value in (
            ("Deployed commit", _esc(report["deployed_commit"])),
            ("Database", _esc(database["path_redacted"])),
            ("Database readable", "yes" if database["reachable"] else "no"),
            ("SQLite journal mode", _display(database["journal_mode"])),
        )
    )
    body = (
        '<section class="hero"><h1>Deployment status</h1>'
        f'<p class="lede"><strong>{_esc(report["status"])}</strong> — read at '
        f'<span class="mono">{_esc(report["generated_at"])}</span>. '
        "Every reading below carries the observation it was taken from and the tolerance it "
        "is judged against.</p>"
        f'<p class="section-note">{_esc(report["status"])} covers serving, the snapshot '
        "refresh, the chain read and the synthetic probes. It does not cover the paid path: "
        f"that was last exercised {_canary_exercised_at(canary)}.</p></section>"
        '<section aria-labelledby="identity-heading">'
        '<h2 id="identity-heading">What is running here</h2>'
        '<div class="table-wrap"><table class="stats-table">'
        "<caption>Read from this process, not from a deployment record.</caption>"
        f"<tbody>{identity_rows}</tbody></table></div></section>"
        '<section aria-labelledby="readings-heading">'
        '<h2 id="readings-heading">What was observed</h2>'
        '<div class="table-wrap"><table class="stats-table">'
        "<caption>One reading per dependency, with the observation time it was taken from."
        "</caption>"
        '<thead><tr><th scope="col">Reading</th><th scope="col">Value</th>'
        '<th scope="col">Observed</th><th scope="col">Tolerance</th>'
        '<th scope="col">Verdict</th></tr></thead>'
        f"<tbody>{reading_rows}</tbody></table></div></section>"
        '<section aria-labelledby="method-heading">'
        '<h2 id="method-heading">How this page was produced</h2>'
        '<div class="panel"><p>Every field on this page is the JSON at '
        '<a href="/api/status">/api/status</a>, rendered — the same reading, not a second '
        f"one. A reading is taken at most once every {REPORT_TTL_S} seconds and stands "
        "until it expires, so the time above is when these figures were observed rather "
        "than when this page was requested. The database readings come from "
        "the same store the API serves from; the BSC reading is one attempt against one "
        "endpoint; the probe counts are rows written by "
        '<span class="mono">docket-probe.service</span>, which exercises this deployment '
        "from outside the application. <strong>down</strong> means the database could not be "
        "read, <strong>degraded</strong> means at least one reading above is out of "
        "tolerance, and <strong>ok</strong> means none is.</p></div></section>"
    )
    if STATUS_CONTENT_MARKER not in shell:
        raise ValueError("status page has no content marker")
    return shell.replace(STATUS_CONTENT_MARKER, body)


def router(
    store: Store,
    *,
    release_commit_path: Path | str | None = None,
    rpc_probe=None,
    canary_service_id: str = "range-doctor",
    ttl_s: int = REPORT_TTL_S,
    clock=time.monotonic,
) -> APIRouter:
    """The status routes, built against one store, one release identity and one cache.

    The shell is read once here rather than per request, for the reason every other page in
    this application is: a missing file should fail the process that ships it, not the one
    request that happened to ask for it. `rpc_probe` is resolved per reading rather than
    bound here, so a caller that supplied none reaches whatever `bounded_rpc_probe` is at
    the moment of the read instead of a copy taken at import. `ttl_s` and `clock` are here
    so the window can be exercised without waiting out a real minute.

    Per process, not per worker set: two uvicorn workers hold two caches and two allowances,
    which doubles the bound rather than removing it. This deployment runs one.
    """
    if release_commit_path is None:
        release_commit_path = default_release_commit_path()
    # Resolved here and not per reading. `RELEASE-commit.txt` is reached through `sys.prefix`,
    # a release flips the symlink under that path while this process is still serving, and a
    # process that read it afterwards would report the incoming release's commit as the code
    # it is running — the one number on this page that must describe this process.
    commit = deployed_commit(release_commit_path)
    shell = (WEB_DIR / "status.html").read_text(encoding="utf-8")
    # Ordered by window start, which keeps expired-window eviction bounded to the expired
    # prefix — the same structure and the same reason as `create_app`'s hire allowances.
    allowances: OrderedDict[str, tuple[float, int]] = OrderedDict()
    api = APIRouter()

    def _build() -> dict:
        return status_report(
            store,
            release_commit_path=release_commit_path,
            now=_utc_now(),
            rpc_probe=rpc_probe or bounded_rpc_probe,
            canary_service_id=canary_service_id,
            commit=commit,
        )

    reading = _ReportCache(_build, ttl_s=ttl_s, clock=clock)

    @api.get("/api/status", response_model=None)
    def api_status(request: Request) -> JSONResponse | dict:
        client_ip = request.client.host if request.client else "unknown"
        resets_in = spend_window(
            allowances,
            client_ip,
            attempts=STATUS_ALLOWANCE,
            window_seconds=STATUS_WINDOW_S,
            clock=clock,
        )
        if resets_in is not None:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(resets_in)},
                content={
                    "error_code": "status_rate_limited",
                    "message": (
                        f"This caller has used its allowance of {STATUS_ALLOWANCE} status "
                        f"reads per {STATUS_WINDOW_S} seconds; it resets in {resets_in}s. "
                        f"One reading stands for {ttl_s}s, so polling faster than that "
                        "returns the same document."
                    ),
                },
            )
        return reading()

    # Unmetered, because it costs a render of a reading that has already been taken and a
    # person who has hit a bound is exactly the person who needs to see this page.
    @api.get("/status", response_class=HTMLResponse, include_in_schema=False)
    def status_html() -> str:
        return status_page(shell, reading())

    return api
