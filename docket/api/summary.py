"""The marketplace counters, and the home page rendered from them.

Every number a visitor reads on the home page comes from here, and every number here is
counted from something durable: rows in `hire_payments`, rows in `canary_runs`, the hire
catalogue, the marketplace registry, and the reconstructed v3 report. Nothing on this
path is typed into markup. A counter written by hand goes stale the first time the
system moves and says nothing about having done so, which is the failure this module
exists to make impossible: the shell carries `<!-- summary-* -->` markers and no digits,
and a marker with no value raises rather than rendering a blank.

Reading `hire_payments` opens its own read-only SQLite connection rather than borrowing
`Store._conn`. `Store` exposes no counting method and its connection is private; a
read-only connection is the smallest honest way to count rows without adding a write
path this module has no business holding. It also lets the two forward-looking counters
ask `sqlite_master` whether their tables exist yet and answer `{}` when they do not,
which is the true answer rather than an error.
"""

import html
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter

from ..hire.admission import resolve_admission

REPO_ROOT = Path(__file__).resolve().parents[2]

# The canary payer prepared on 2026-08-24 and recorded in `docs/deployment-runbook.md`.
#
# How a canary settlement is identified, and why it is this and nothing else: the paid
# path opens for a service that is not admitted only when the request carried an accepted
# `X-Docket-Canary` credential (`routes.py:2205` and `routes.py:2471`), but that header is
# never persisted — `Store.reserve_payment` stores the payer, the recipient, the asset,
# the amount, the resource and the hashes, and no canary flag. The payer address is
# therefore the only durable discriminator a settled row carries, and it is the one used
# here. `tests/test_marketplace_summary.py` pins the constant to the runbook so the
# identity cannot rot silently.
CANARY_PAYER = "0x4821b5445f1ce8328806f83bafbdbe7d668e6fd3"

# Counted as settlements. `verified`, `output_ready`, `settling`, `failed_no_charge`,
# `settlement_failed` and `settlement_unknown` are not settlements: only `settled` is
# reached from `Store.finish_payment`, which requires a transaction id and a network.
SETTLED_STATUS = "settled"

# What activating any service in this build costs a caller in permissions, and what it
# leaves them able to undo. Stated per listing rather than measured because it is a
# property of the build and not of a run: no service here holds a session key, a signer
# or a submitter, so there is nothing standing to revoke. When bounded sessions land,
# these become per-service facts read from the activation record.
NO_STANDING_PERMISSION = (
    "Nothing standing to revoke: a run is one bounded request that ends when its result "
    "is returned, and Docket keeps no permission afterwards."
)
FREE_TIER_PERMISSIONS = (
    "None. The public sample needs no account, wallet, key or approval."
)


NOT_MEASURED = "not yet measured"


def _esc(value) -> str:
    return html.escape(str(value))


def _iso_z(moment: datetime) -> str:
    """Whole seconds, UTC. Microseconds on a counter timestamp assert a precision the
    count does not have and make two adjacent renderings look like different readings."""
    return (
        moment.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _display_moment(value) -> str:
    """A stored ISO timestamp as a reader sees it, or the absent marker."""
    if not isinstance(value, str) or not value:
        return NOT_MEASURED
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return NOT_MEASURED
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _read_only(store):
    """A closing read-only connection to the store's database.

    `contextlib.closing` rather than the connection's own context manager: that one
    commits, and nothing here writes. Read-only is enforced by SQLite itself through the
    URI rather than by this module remembering not to.
    """
    connection = sqlite3.connect(f"{store.path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return closing(connection)


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    """The columns of `table`, or an empty set when no such table exists yet.

    Two counters name tables other lanes are still building. An absent table is not an
    error and not a zero to be invented: it is a population that does not exist, and the
    counter it feeds returns an empty mapping.
    """
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if exists is None:
        return set()
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}


def _settlement_counts(connection: sqlite3.Connection) -> tuple[int, int]:
    """Settled hire payments split into public ones and the internal canary's."""
    rows = connection.execute(
        "SELECT payer, COUNT(*) AS settled FROM hire_payments "
        "WHERE status = ? GROUP BY payer",
        (SETTLED_STATUS,),
    ).fetchall()
    canary = sum(
        int(row["settled"]) for row in rows if str(row["payer"]).lower() == CANARY_PAYER
    )
    total = sum(int(row["settled"]) for row in rows)
    return total - canary, canary


def _canary_history(connection: sqlite3.Connection, service_id: str) -> dict:
    """One service's canary record: how many runs, how many passed, when, over what."""
    row = connection.execute(
        "SELECT COUNT(*) AS runs, "
        "SUM(CASE WHEN verdict = 'passed' THEN 1 ELSE 0 END) AS passed, "
        "MIN(started_at) AS first_started, MAX(started_at) AS last_started "
        "FROM canary_runs WHERE service_id = ?",
        (service_id,),
    ).fetchone()
    latest_pass = connection.execute(
        "SELECT finished_at FROM canary_runs "
        "WHERE service_id = ? AND verdict = 'passed' AND finished_at IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (service_id,),
    ).fetchone()
    return {
        "runs": int(row["runs"] or 0),
        "passed": int(row["passed"] or 0),
        "first_started": row["first_started"],
        "last_started": row["last_started"],
        "last_pass_finished": latest_pass["finished_at"] if latest_pass else None,
    }


@lru_cache(maxsize=4)
def _checkout_commit(repo_root: Path) -> str:
    """The working checkout's commit, read once per process.

    Guarded on `.git` existing so an installed package never pays for a subprocess that
    was always going to fail, and cached because a served process cannot change the
    commit it is running.
    """
    if not (repo_root / ".git").exists():
        return "source"
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "source"
    return completed.stdout.strip() or "source"


def _deployed_commit(release_commit_path: Path | None) -> str:
    """What this process is running, said in the strongest form available.

    `deploy/release.sh` writes `RELEASE-commit.txt` into the release virtualenv root, so
    a deployed process reads its own identity from beside its package. A source checkout
    has no such file and answers with its checkout commit; anything else answers
    `"source"` rather than guessing.
    """
    path = (
        Path(sys.prefix) / "RELEASE-commit.txt"
        if release_commit_path is None
        else Path(release_commit_path)
    )
    try:
        recorded = path.read_text(encoding="utf-8").strip()
    except OSError:
        recorded = ""
    if recorded:
        return recorded
    return _checkout_commit(REPO_ROOT)


def marketplace_summary(
    store,
    *,
    v3_report: dict,
    services: list,
    release_commit_path: Path | None = None,
    now=None,
) -> dict:
    """Count what the marketplace currently is, from the records that hold it.

    `services` is the marketplace registry's `ServiceRecord` list: it reaches both the
    hire catalogue terms and the on-chain identity a listing shows. `public_paid_hires`
    and `canary_settlements` partition the settled `hire_payments` rows by payer, using
    the rule documented at `CANARY_PAYER`. `services_paid_stock` re-resolves admission
    against the latest canary run rather than reading the static limb, so a stale canary
    closes the shelf here exactly as it does at `/services`.
    """
    observed = now or datetime.now(timezone.utc)
    with _read_only(store) as connection:
        public_paid_hires, canary_settlements = _settlement_counts(connection)
        activations_by_state = {}
        if "state" in _table_columns(connection, "activations"):
            activations_by_state = {
                str(row["state"]): int(row["activations"])
                for row in connection.execute(
                    "SELECT state, COUNT(*) AS activations FROM activations "
                    "GROUP BY state ORDER BY state"
                )
            }
        external_listings_by_level = {}
        if "verification_level" in _table_columns(connection, "external_listings"):
            external_listings_by_level = {
                str(row["verification_level"]): int(row["listings"])
                for row in connection.execute(
                    "SELECT verification_level, COUNT(*) AS listings "
                    "FROM external_listings GROUP BY verification_level "
                    "ORDER BY verification_level"
                )
            }
    paid_stock = sum(
        resolve_admission(
            record.offer, store.latest_canary_run(record.service_id), now=observed
        ).passes
        for record in services
    )
    return {
        "services_total": len(services),
        "services_paid_stock": paid_stock,
        "public_paid_hires": public_paid_hires,
        "canary_settlements": canary_settlements,
        "erc8004_identities": sum(
            record.agent_id is not None and record.category is not None
            for record in services
        ),
        "v3_families": v3_report.get("summary", {}).get("n_families", 0),
        "external_listings_by_level": external_listings_by_level,
        "activations_by_state": activations_by_state,
        "deployed_commit": _deployed_commit(release_commit_path),
        "generated_at": _iso_z(observed),
    }


def listing_facts(store, services: list) -> list[dict]:
    """The same ten fields for every listing, absent ones named rather than dropped.

    A grid whose cards each answer a different set of questions cannot be compared, so
    each listing answers all ten and writes the absent marker where the record holds
    nothing. Verification, success counts and the measurement window come from
    `canary_runs`; the price, the permissions and the custody model come from the hire
    catalogue and its admission limbs; the identity comes from the registry.
    """
    with _read_only(store) as connection:
        history = {
            record.service_id: _canary_history(connection, record.service_id)
            for record in services
        }
    facts = []
    for record in services:
        canary = history[record.service_id]
        window = NOT_MEASURED
        if canary["runs"]:
            window = (
                f"{_display_moment(canary['first_started'])} to "
                f"{_display_moment(canary['last_started'])}"
            )
        admission = resolve_admission(
            record.offer, store.latest_canary_run(record.service_id)
        )
        evidence = record.evidence[0] if record.evidence else None
        facts.append(
            {
                "service_id": record.service_id,
                "name": record.name,
                "category": record.category.value if record.category else None,
                "job": record.offer.job_summary,
                "identity": (
                    f"ERC-8004 agent {record.agent_id.rsplit(':', 1)[1]} on BSC chain 56"
                    if record.agent_id
                    else "No BSC identity registered for this service"
                ),
                "last_verification": _display_moment(canary["last_pass_finished"]),
                "success_count": (
                    f"{canary['passed']}/{canary['runs']} recorded canary runs passed"
                    if canary["runs"]
                    else NOT_MEASURED
                ),
                "measurement_window": window,
                "price": f"{record.price_display} per completed run",
                "custody": (
                    "Non-custodial. Docket holds no key and no funds for you; a settled "
                    f"hire pulls exactly {record.price_display} through the "
                    "authorization you signed and moves nothing else."
                ),
                "permissions": (
                    f"An exact-amount {record.price_display} authorization, never an "
                    "unlimited approval."
                    if admission.passes
                    else FREE_TIER_PERMISSIONS
                ),
                "revocation": NO_STANDING_PERMISSION,
                "evidence_url": evidence.url
                if evidence
                else f"/services/{record.service_id}",
                "evidence_label": (
                    evidence.label if evidence else "Machine-readable catalogue entry"
                ),
            }
        )
    return facts


def _listing_card(listing: dict) -> str:
    """One listing, answering all ten questions in the order every other listing does.

    The evidence link sits in the field list rather than beside the action, so a reader
    comparing two cards finds it in the same place on both and reads the record's own
    label for it rather than a house word standing in for one.
    """
    rows = (
        ("Job", listing["job"]),
        ("BSC identity", listing["identity"]),
        ("Last successful verification", listing["last_verification"]),
        ("Successful runs", listing["success_count"]),
        ("Measurement window", listing["measurement_window"]),
        ("Price", listing["price"]),
        ("Custody", listing["custody"]),
        ("Required permissions", listing["permissions"]),
        ("Cancellation and revocation", listing["revocation"]),
    )
    definitions = "".join(
        f"<dt>{_esc(label)}</dt><dd>{_esc(value)}</dd>" for label, value in rows
    )
    return (
        f'<article class="listing-card" data-listing-id="{_esc(listing["service_id"])}">'
        f"<h3>{_esc(listing['name'])}</h3>"
        f'<dl class="listing-facts">{definitions}'
        f'<dt>Evidence</dt><dd><a href="{_esc(listing["evidence_url"])}">'
        f"{_esc(listing['evidence_label'])}</a></dd></dl>"
        '<p class="listing-actions">'
        f'<a href="/activate?service={_esc(listing["service_id"])}">Activate</a>'
        f'<a href="/service?id={_esc(listing["service_id"])}">Inspect</a>'
        "</p></article>"
    )


def home_page(shell: str, summary: dict, listings: list[dict]) -> str:
    """Fill the home shell from the summary object, or refuse to serve it.

    The same discipline `web_pages.py` applies to the other server-rendered shells: a
    marker the shell does not carry is a page that would have shipped a blank counter,
    so it raises here rather than reaching a reader.
    """
    # Four and four today, and two different quantities: `erc8004_identities` counts the
    # identities Docket registered, this counts the services Docket declared into one of
    # the four categories. A label whose number answers a neighbouring question is the
    # drift this page was rebuilt to remove, so the heading counts its own.
    category_services = sum(1 for listing in listings if listing["category"])
    replacements = {
        "<!-- summary-public-paid-hires -->": f"{summary['public_paid_hires']:,}",
        "<!-- summary-canary-settlements -->": f"{summary['canary_settlements']:,}",
        "<!-- summary-services-paid-stock -->": f"{summary['services_paid_stock']:,}",
        "<!-- summary-services-total -->": f"{summary['services_total']:,}",
        "<!-- summary-erc8004-identities -->": f"{summary['erc8004_identities']:,}",
        "<!-- summary-category-services -->": f"{category_services:,}",
        "<!-- summary-v3-families -->": f"{summary['v3_families']:,}",
        "<!-- summary-generated-at -->": _esc(summary["generated_at"]),
        "<!-- summary-deployed-commit -->": _esc(summary["deployed_commit"]),
        "<!-- marketplace-listings -->": "".join(
            _listing_card(listing) for listing in listings
        ),
    }
    rendered = shell
    for marker, body in replacements.items():
        if marker not in rendered:
            raise ValueError(f"home page carries no {marker}")
        rendered = rendered.replace(marker, body)
    return rendered


def summary_router(store, v3_report: dict, services: list) -> APIRouter:
    """The one route this module serves, recomputed per request.

    The home page is pinned at startup so two readers of the same process are never
    served two different pages; the JSON is not, because an agent asking for the current
    state should get the current state — the same split `/services` already makes when it
    re-resolves admission per request.
    """
    router = APIRouter()

    @router.get("/api/marketplace/summary", include_in_schema=False)
    def marketplace_summary_route() -> dict:
        return marketplace_summary(store, v3_report=v3_report, services=services)

    return router
