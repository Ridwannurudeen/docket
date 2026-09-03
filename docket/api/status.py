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
"""

import html
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from ..escrow import constants as escrow_constants
from ..escrow.chain import Rpc
from ..store import COMPLETE_STOP_REASON, PROBE_WINDOW_HOURS, Store

WEB_DIR = Path(__file__).resolve().parent / "web"
STATUS_CONTENT_MARKER = "<!-- status-content -->"

# One request per endpoint, so a status read cannot outlive the page a person is waiting on
# by more than the failover list allows: RPC_TIMEOUT_S x ATTEMPTS_PER_RPC x len(RPC_URLS).
RPC_TIMEOUT_S = 5
# `docket-refresh.timer` fires every six hours. Two scheduled windows is the boundary between
# a run that has not landed yet and a refresh that is not running, and the second is the one
# an operator has to act on.
REFRESH_MAX_AGE_SECONDS = 12 * 3600
REFRESH_INTERVAL_SECONDS = 6 * 3600
DB_TIMEOUT_S = 5
GIT_TIMEOUT_S = 5
# The verdict that means the canary ran and something it checked was wrong. The other two
# terminal verdicts describe a canary that did not exercise a limb, which is a configuration
# state rather than a fault.
CANARY_FAILED_VERDICT = "failed"


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
    snapshot_id = store.latest_snapshot_id()
    row = store.snapshot(snapshot_id) if snapshot_id is not None else {}
    at = row.get("finished_at") or row.get("started_at")
    sampled = row.get("sampled")
    expected = row.get("expected")
    # The predicate `promote_snapshot` uses, recomputed rather than read off `promoted_at`:
    # this page reports on the newest sweep, and a newest sweep that is still running has no
    # promotion to read.
    complete = bool(
        row.get("finished_at")
        and sampled is not None
        and expected is not None
        and sampled == expected
        and sampled > 0
        and row.get("stop_reason") in (None, COMPLETE_STOP_REASON)
    )
    return {"at": at, "age_seconds": _age_seconds(at, now), "complete": complete}


def _latest_canary(store: Store, service_id: str, now: datetime) -> dict:
    run = store.latest_canary_run(service_id)
    finished_at = run.get("finished_at")
    return {
        "verdict": run.get("verdict"),
        "finished_at": finished_at,
        "age_seconds": _age_seconds(finished_at, now),
    }


def _probes(store: Store, now: datetime) -> dict:
    runs = store.latest_probe_runs(PROBE_WINDOW_HOURS, now=now)
    return {
        "last_run_at": runs[0]["started_at"] if runs else None,
        "ok_count": sum(1 for run in runs if run["ok"]),
        "fail_count": sum(1 for run in runs if not run["ok"]),
        "window_hours": PROBE_WINDOW_HOURS,
    }


def _session(url: str) -> Web3:
    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": RPC_TIMEOUT_S}))
    # BSC is PoA: 280-byte extraData, which a block read rejects without this.
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def bounded_rpc_probe() -> dict:
    """One `eth_blockNumber` through the shared failover list, capped at RPC_TIMEOUT_S per
    request. `latency_ms` is the whole call including any failover, so a slow reading and a
    reading that took three endpoints to obtain are not published as the same number."""
    rpc = Rpc(session_factory=_session)
    started = time.monotonic()
    try:
        block_number = int(rpc(lambda w3: w3.eth.block_number))
    # Every endpoint failing raises RuntimeError, but a socket, a proxy or a malformed
    # response can arrive as anything; none of them is this process being wrong.
    except Exception:
        block_number = None
    latency_ms = round((time.monotonic() - started) * 1000)
    return {
        "endpoint_host": urlsplit(rpc.used).hostname if rpc.used else None,
        "ok": block_number is not None,
        "block_number": block_number,
        "latency_ms": latency_ms,
    }


def refresh_out_of_tolerance(refresh: dict) -> bool:
    age = refresh["age_seconds"]
    return not refresh["complete"] or age is None or age > REFRESH_MAX_AGE_SECONDS


def status_report(
    store: Store,
    *,
    release_commit_path: Path | str,
    now: datetime,
    rpc_probe,
    canary_service_id: str = "range-doctor",
) -> dict:
    reachable = True
    try:
        refresh = _latest_refresh(store, now)
        canary = _latest_canary(store, canary_service_id, now)
        probes = _probes(store, now)
    # The store refuses a database whose journal mode is not DELETE with a RuntimeError, and
    # a deleted or corrupt file arrives as sqlite3.Error. Both are the same fact for a reader:
    # this deployment cannot read its own record.
    except (sqlite3.Error, RuntimeError, OSError):
        reachable = False
        refresh = {"at": None, "age_seconds": None, "complete": False}
        canary = {"verdict": None, "finished_at": None, "age_seconds": None}
        probes = {
            "last_run_at": None,
            "ok_count": 0,
            "fail_count": 0,
            "window_hours": PROBE_WINDOW_HOURS,
        }
    rpc = rpc_probe()

    if not reachable:
        status = "down"
    elif (
        refresh_out_of_tolerance(refresh)
        or canary["verdict"] == CANARY_FAILED_VERDICT
        or not rpc["ok"]
        or probes["fail_count"] > 0
    ):
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "deployed_commit": deployed_commit(release_commit_path),
        "db": {
            "reachable": reachable,
            "journal_mode": _journal_mode(Path(store.path)),
            "path_redacted": _redacted(Path(store.path)),
        },
        "latest_refresh": refresh,
        "latest_canary": canary,
        "rpc": rpc,
        "probes": probes,
        "generated_at": now.isoformat(),
    }


def _esc(value) -> str:
    return html.escape(str(value))


def _display(value) -> str:
    return "not recorded" if value in (None, "") else _esc(value)


def _aged(label: str, age: int | None) -> str:
    """A reading with no observation behind it has no age either, and appending one anyway
    is how "not recorded, not recorded old" reaches a page."""
    return label if age is None else f"{label}, {age:,}s old"


def status_page(shell: str, report: dict) -> str:
    """Render the served document. Every row states the reading, the observation it was taken
    from, and the tolerance it is judged against, so a reader can check the verdict rather
    than take it."""
    refresh = report["latest_refresh"]
    canary = report["latest_canary"]
    rpc = report["rpc"]
    probes = report["probes"]
    database = report["db"]
    runs = probes["ok_count"] + probes["fail_count"]

    rows = (
        (
            "Snapshot refresh",
            _aged(
                "complete" if refresh["complete"] else "not complete",
                refresh["age_seconds"],
            ),
            _display(refresh["at"]),
            f"complete and under {REFRESH_MAX_AGE_SECONDS:,}s "
            f"(two {REFRESH_INTERVAL_SECONDS:,}s refresh windows)",
            refresh_out_of_tolerance(refresh),
        ),
        (
            "Service canary",
            _aged(_display(canary["verdict"]), canary["age_seconds"]),
            _display(canary["finished_at"]),
            f"any verdict other than {CANARY_FAILED_VERDICT}; a canary that has not run is "
            "not counted against this deployment",
            canary["verdict"] == CANARY_FAILED_VERDICT,
        ),
        (
            "BSC read",
            (
                f"block {rpc['block_number']:,} in {rpc['latency_ms']:,}ms"
                if rpc["ok"]
                else f"no endpoint answered in {rpc['latency_ms']:,}ms"
            ),
            _display(rpc["endpoint_host"]),
            f"one eth_blockNumber, {RPC_TIMEOUT_S}s per request, failing over "
            f"{len(escrow_constants.RPC_URLS)} endpoints",
            not rpc["ok"],
        ),
        (
            "Synthetic probes",
            f"{probes['ok_count']} of {runs} runs passed",
            _display(probes["last_run_at"]),
            f"0 failed runs in the last {probes['window_hours']} hours",
            probes["fail_count"] > 0,
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
        "is judged against.</p></section>"
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
        '<a href="/api/status">/api/status</a>, rendered. The database readings come from '
        "the same store the API serves from; the BSC reading is made when the page is "
        "requested; the probe counts are rows written by "
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
) -> APIRouter:
    """The status routes, built against one store and one release identity.

    The shell is read once here rather than per request, for the reason every other page in
    this application is: a missing file should fail the process that ships it, not the one
    request that happened to ask for it. `rpc_probe` is resolved per request rather than
    bound here, so a caller that supplied none reaches whatever `bounded_rpc_probe` is at
    the moment of the read instead of a copy taken at import.
    """
    if release_commit_path is None:
        release_commit_path = default_release_commit_path()
    shell = (WEB_DIR / "status.html").read_text(encoding="utf-8")
    api = APIRouter()

    def _report() -> dict:
        return status_report(
            store,
            release_commit_path=release_commit_path,
            now=_utc_now(),
            rpc_probe=rpc_probe or bounded_rpc_probe,
            canary_service_id=canary_service_id,
        )

    @api.get("/api/status")
    def api_status() -> dict:
        return _report()

    @api.get("/status", response_class=HTMLResponse, include_in_schema=False)
    def status_html() -> str:
        return status_page(shell, _report())

    return api
