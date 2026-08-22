import sqlite3
from pathlib import Path

import pytest

from docket.store import Store

ROW = {
    "agent_id": "56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:136384",
    "token_id": "136384",
    "chain_id": 56,
    "contract_address": "0x8004a169fb4a3325136eb29fa0ceb6d2e539a432",
    "owner_address": "0xe4fe23fb57dbb9ac2f685ea29b6b9a1409a0d359",
    "name": "Agent #136384",
    "description": None,
    "supported_protocols": [],
    "x402_supported": True,
    "is_verified": False,
    "total_feedbacks": 0,
    "total_score": 0.0,
    "created_at": "2026-06-16T15:03:30Z",
}

CANARY_CHECKS = [
    {
        "leg": "fresh_browser_surface",
        "checked": "a fresh client received the public landing page",
        "status": "passed",
        "observed": {"status_code": 200, "content_type": "text/html"},
        "evidence": {"path": "/", "body_sha256": "0xabc"},
    }
]


def test_snapshot_roundtrip(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=243421)
    assert store.upsert_agents([ROW], sid) == 1
    store.finish_snapshot(sid, sampled=1)
    assert store.agent_count(sid) == 1
    got = next(store.iter_agents(sid))
    assert got["agent_id"] == ROW["agent_id"]
    assert got["supported_protocols"] == []  # round-trips as a list, not a JSON string
    assert got["x402_supported"] is True  # round-trips as bool, not 0/1


def test_upsert_is_idempotent_and_updates(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    store.upsert_agents([ROW], sid)
    store.upsert_agents([{**ROW, "name": "SOLVENT", "total_feedbacks": 3}], sid)
    assert store.agent_count(sid) == 1  # no duplicate row
    got = next(store.iter_agents(sid))
    assert got["name"] == "SOLVENT"  # latest write wins
    assert got["total_feedbacks"] == 3


def test_upsert_refreshes_transferred_owner(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    store.upsert_agents([ROW], sid)
    new_owner = "0x1111111111111111111111111111111111111111"
    store.upsert_agents([{**ROW, "owner_address": new_owner}], sid)
    assert store.agent_count(sid) == 1
    got = next(store.iter_agents(sid))
    assert (
        got["owner_address"] == new_owner
    )  # ownership transfers; a stale owner breaks clustering


def test_token_id_coercion_handles_zero_and_null(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    absent = {**ROW, "agent_id": "absent"}
    del absent["token_id"]
    store.upsert_agents(
        [
            {**ROW, "agent_id": "zero", "token_id": 0},
            {**ROW, "agent_id": "null", "token_id": None},
            {**ROW, "agent_id": "text", "token_id": "257920"},
            absent,
        ],
        sid,
    )
    stored = {a["agent_id"]: a["token_id"] for a in store.iter_agents(sid)}
    assert (
        stored["zero"] == "0"
    )  # integer zero is a legitimate token id, not falsy-empty
    assert stored["null"] == ""  # not the literal string "None"
    assert stored["text"] == "257920"
    assert stored["absent"] == ""


def test_snapshot_records_partial_coverage(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=100)
    store.upsert_agents([ROW], sid)
    store.finish_snapshot(sid, sampled=1)
    with sqlite3.connect(tmp_path / "d.sqlite3") as conn:
        row = conn.execute(
            "SELECT expected, sampled, finished_at FROM snapshots WHERE id = ?", (sid,)
        ).fetchone()
    assert row[0] == 100 and row[1] == 1 and row[2] is not None


def test_snapshot_records_the_population_it_swept(tmp_path: Path):
    """`expected` states how many rows the query claimed. `population` states which query —
    without it, 506 of 506 reads as a whole-registry census."""
    store = Store(tmp_path / "d.sqlite3")
    filtered = store.begin_snapshot(
        chain_id=56, expected=506, population="min_feedbacks>=1"
    )
    store.finish_snapshot(filtered, sampled=506)
    assert store.snapshot(filtered)["population"] == "min_feedbacks>=1"
    whole = store.begin_snapshot(chain_id=56, expected=9, population="all")
    assert store.snapshot(whole)["population"] == "all"


def test_registry_total_is_the_largest_total_any_sweep_recorded(tmp_path: Path):
    """The only chain-wide figure Docket holds. A filtered snapshot is unreadable without it:
    506 of 506 is complete, and complete is a fraction of a percent of the chain."""
    store = Store(tmp_path / "d.sqlite3")
    assert store.registry_total(56) is None  # nothing swept, nothing to claim
    full = store.begin_snapshot(chain_id=56, expected=247065, population="all")
    store.finish_snapshot(full, sampled=2000)
    crashed = store.begin_snapshot(chain_id=56, expected=247146, population="all")
    filtered = store.begin_snapshot(
        chain_id=56, expected=506, population="min_feedbacks>=1"
    )
    store.finish_snapshot(filtered, sampled=506)
    # The crashed sweep's `expected` still counts: it is what the API answered when asked,
    # recorded before the sweep died, and it does not depend on the sweep finishing.
    assert store.registry_total(56) == 247146
    assert store.snapshot(crashed)["sampled"] is None
    assert (
        store.registry_total(97) is None
    )  # another chain's sweeps are not this chain's


def test_registry_total_is_only_a_lower_bound_when_every_sweep_was_filtered(
    tmp_path: Path,
):
    """The state Stage 5's refresh loop produces on a fresh deployment: nothing but targeted
    sweeps on record. The largest total recorded is then a FILTERED total, and the chain is
    larger than it rather than equal to it — so the figure may only ever be read as "at least
    this many", never as the size of the registry."""
    store = Store(tmp_path / "d.sqlite3")
    for expected in (506, 512):
        sid = store.begin_snapshot(
            chain_id=56, expected=expected, population="min_feedbacks>=1"
        )
        store.finish_snapshot(sid, sampled=expected)
    assert store.registry_total(56) == 512  # a filtered total, and a true lower bound
    # It can equal the served snapshot's own `expected`, which is why no doc may promise it
    # is "never the served snapshot's own figure".
    assert store.registry_total(56) == store.snapshot(2)["expected"]


def test_registry_total_states_the_lower_bound_reading_where_a_reader_will_see_it():
    doc = Store.registry_total.__doc__.lower()
    assert "lower bound" in doc
    assert "at least" in doc


def test_a_database_predating_the_column_is_migrated_not_rejected(tmp_path: Path):
    """The live database was written before this column existed. Its rows cannot state a
    population they never recorded, so they read as None — unspecified, never guessed at."""
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """CREATE TABLE snapshots (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   chain_id INTEGER NOT NULL,
                   expected INTEGER,
                   sampled INTEGER,
                   started_at TEXT NOT NULL,
                   finished_at TEXT
               );
               INSERT INTO snapshots (chain_id, expected, sampled, started_at, finished_at)
               VALUES (56, 506, 506, '2026-08-07T17:50:23+00:00', '2026-08-07T17:51:02+00:00');"""
        )
    store = Store(path)
    assert store.snapshot(1)["population"] is None
    assert store.snapshot(1)["promoted_at"] == "2026-08-07T17:51:02+00:00"
    assert store.latest_complete_snapshot_id(56) == 1  # still readable, still servable
    fresh = store.begin_snapshot(chain_id=56, expected=1, population="all")
    assert store.snapshot(fresh)["population"] == "all"


def test_a_payment_table_predating_operator_recovery_is_migrated(tmp_path: Path):
    path = tmp_path / "legacy-payments.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """CREATE TABLE hire_payments (
                   nonce TEXT PRIMARY KEY,
                   payment_id TEXT NOT NULL UNIQUE,
                   service_id TEXT NOT NULL,
                   payer TEXT NOT NULL,
                   recipient TEXT NOT NULL,
                   asset TEXT NOT NULL,
                   amount TEXT NOT NULL,
                   resource TEXT NOT NULL,
                   input_hash TEXT NOT NULL,
                   output_hash TEXT,
                   status TEXT NOT NULL,
                   result_json TEXT,
                   receipt_json TEXT,
                   transaction_id TEXT,
                   network TEXT,
                   error TEXT,
                   created_at TEXT NOT NULL,
                   updated_at TEXT NOT NULL
               );"""
        )

    Store(path)

    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(hire_payments)")}
    assert "operator_recovered_at" in columns


def test_latest_complete_snapshot_skips_a_sweep_that_never_finished(tmp_path: Path):
    """A crashed or in-flight sweep is the newest ROW, and its counts are still moving. The
    live database carries exactly this: snapshot 2 was begun on 2026-08-07 and never closed."""
    store = Store(tmp_path / "d.sqlite3")
    first = store.begin_snapshot(chain_id=56, expected=10)
    store.finish_snapshot(first, sampled=10)
    crashed = store.begin_snapshot(chain_id=56, expected=10)
    assert (
        store.latest_snapshot_id(56) == crashed
    )  # the newest row, still the newest row
    assert store.latest_complete_snapshot_id(56) == first  # never the unfinished one

    third = store.begin_snapshot(chain_id=56, expected=10)
    store.finish_snapshot(third, sampled=10)
    assert store.latest_complete_snapshot_id(56) == third  # a later finish wins again


def test_a_finished_candidate_stays_hidden_until_explicit_promotion(tmp_path: Path):
    store = Store(tmp_path / "promotion.sqlite3")
    current = store.begin_snapshot(chain_id=56, expected=1)
    store.finish_snapshot(current, sampled=1)
    candidate = store.begin_snapshot(chain_id=56, expected=2)

    store.finish_snapshot(candidate, sampled=2, promote=False)

    assert store.snapshot(candidate)["promoted_at"] is None
    assert store.latest_complete_snapshot_id(56) == current
    store.promote_snapshot(candidate)
    assert store.snapshot(candidate)["promoted_at"] is not None
    assert store.latest_complete_snapshot_id(56) == candidate


@pytest.mark.parametrize(
    ("sampled", "expected", "stop_reason"),
    ((1, 2, "exhausted"), (1, 1, "max_pages"), (0, 0, "exhausted")),
)
def test_explicit_promotion_refuses_an_incomplete_candidate(
    tmp_path: Path, sampled: int, expected: int, stop_reason: str
):
    store = Store(tmp_path / f"promotion-{stop_reason}-{sampled}.sqlite3")
    candidate = store.begin_snapshot(chain_id=56, expected=expected)
    store.finish_snapshot(
        candidate,
        sampled=sampled,
        expected=expected,
        stop_reason=stop_reason,
        promote=False,
    )

    with pytest.raises(ValueError, match="cannot be promoted"):
        store.promote_snapshot(candidate)

    assert store.latest_complete_snapshot_id(56) is None


def test_finish_snapshot_does_not_mark_incomplete_counts_as_promoted(tmp_path: Path):
    store = Store(tmp_path / "write-side-promotion.sqlite3")
    snapshot = store.begin_snapshot(chain_id=56, expected=2)

    store.finish_snapshot(snapshot, sampled=1, stop_reason="exhausted")

    row = store.snapshot(snapshot)
    assert row["finished_at"] is not None
    assert row["promoted_at"] is None


def test_latest_complete_snapshot_is_per_chain_and_none_when_nothing_finished(
    tmp_path: Path,
):
    store = Store(tmp_path / "d.sqlite3")
    store.begin_snapshot(chain_id=56, expected=10)
    assert store.latest_complete_snapshot_id(56) is None  # no finished sweep to serve
    other = store.begin_snapshot(chain_id=97, expected=4)
    store.finish_snapshot(other, sampled=4)
    assert (
        store.latest_complete_snapshot_id(56) is None
    )  # another chain's is not this chain's
    assert store.latest_complete_snapshot_id(97) == other


def test_endpoints_roundtrip_and_upsert_is_idempotent(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    rows = [
        {"agent_id": "56:r:1", "kind": "a2a", "url": "https://a.example/agent"},
        {"agent_id": "56:r:1", "kind": "mcp", "url": "https://a.example/mcp"},
    ]
    assert store.upsert_endpoints(rows, sid) == 2
    store.upsert_endpoints(rows, sid)  # same rows again
    assert store.endpoint_count(sid) == 2  # no duplicates
    kinds = {e["kind"] for e in store.iter_endpoints(sid)}
    assert kinds == {"a2a", "mcp"}
    assert [e["url"] for e in store.iter_endpoints(sid, kind="mcp")] == [
        "https://a.example/mcp"
    ]


def test_enriched_agent_ids_reports_what_has_been_processed(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    store.upsert_endpoints(
        [{"agent_id": "56:r:1", "kind": "a2a", "url": "https://a/x"}], sid
    )
    store.mark_enriched(["56:r:1", "56:r:2"], sid)  # r:2 had no endpoints at all
    assert store.enriched_agent_ids(sid) == {"56:r:1", "56:r:2"}


def test_liveness_rows_are_append_only_observations(tmp_path: Path):
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=None)
    obs = {
        "snapshot_id": sid,
        "agent_id": "56:r:1",
        "url": "https://a/x",
        "observed_at": "2026-08-07T10:00:00+00:00",
        "outcome": "responded",
        "status_code": 200,
        "elapsed_ms": 143,
        "detail": None,
    }
    assert store.record_liveness([obs]) == 1
    assert (
        store.record_liveness(
            [
                {
                    **obs,
                    "observed_at": "2026-08-07T11:00:00+00:00",
                    "outcome": "timeout",
                    "status_code": None,
                    "elapsed_ms": 8000,
                    "detail": "ReadTimeout",
                }
            ]
        )
        == 1
    )
    seen = list(store.iter_liveness(sid))
    assert len(seen) == 2  # history is kept, not overwritten
    assert {s["outcome"] for s in seen} == {"responded", "timeout"}


def test_a_finished_but_truncated_sweep_is_never_promoted(tmp_path: Path):
    """`finished_at` caught the crashed sweep and missed the truncated one.

    `_sweep` leaves its loop on a page cap or a paginator that stops advancing, and then closes
    the snapshot exactly as a clean run does. Both are finished; only one reached the end of the
    query. Serving the other publishes understated counts as the whole of what Docket observed —
    the failure the crashed-sweep guard was written to prevent, arriving by the other door.
    """
    store = Store(tmp_path / "d.sqlite3")
    clean = store.begin_snapshot(chain_id=56, expected=10)
    store.finish_snapshot(clean, sampled=10, stop_reason="exhausted")

    capped = store.begin_snapshot(chain_id=56, expected=10)
    store.finish_snapshot(capped, sampled=4, expected=10, stop_reason="max_pages")
    assert store.latest_snapshot_id(56) == capped  # newest row, as always
    assert store.latest_complete_snapshot_id(56) == clean  # but never served

    stuck = store.begin_snapshot(chain_id=56, expected=10)
    store.finish_snapshot(stuck, sampled=7, expected=10, stop_reason="not_advancing")
    assert store.latest_complete_snapshot_id(56) == clean


def test_a_sweep_that_ended_cleanly_but_short_is_not_complete_either(tmp_path: Path):
    """`exhausted` says the paginator ran out, not that the query was covered. If the API
    claimed 10 and 6 were stored, the gap is real whatever the reason, and `coverage_report`
    already calls that partial — this predicate must agree with it rather than serve a
    snapshot the coverage page would label incomplete."""
    store = Store(tmp_path / "d.sqlite3")
    short = store.begin_snapshot(chain_id=56, expected=10)
    store.finish_snapshot(short, sampled=6, expected=10, stop_reason="exhausted")
    assert store.latest_complete_snapshot_id(56) is None


def test_a_snapshot_written_before_stop_reason_existed_is_judged_on_its_counts(
    tmp_path: Path,
):
    """The live database holds snapshot 3: 506 of 506, run and checked by hand, and NULL in a
    column that did not exist when it was written. Rejecting it would take the site's only
    served capture offline to fix a bug it does not have."""
    store = Store(tmp_path / "d.sqlite3")
    legacy = store.begin_snapshot(chain_id=56, expected=506)
    store.finish_snapshot(legacy, sampled=506)
    with store._conn() as conn:  # simulate a row written before the migration
        conn.execute("UPDATE snapshots SET stop_reason = NULL WHERE id = ?", (legacy,))
    assert store.latest_complete_snapshot_id(56) == legacy


def test_an_unknown_stop_reason_is_refused_rather_than_stored(tmp_path: Path):
    """An open vocabulary would let a new stop condition arrive unclassified and be served as
    a clean finish — the exact shape of the bug this column closes."""
    store = Store(tmp_path / "d.sqlite3")
    sid = store.begin_snapshot(chain_id=56, expected=1)
    with pytest.raises(ValueError, match="unknown stop_reason"):
        store.finish_snapshot(sid, sampled=1, stop_reason="gave_up")


def test_a_new_store_does_not_invent_canary_history(tmp_path: Path):
    store = Store(tmp_path / "empty-canary.sqlite3")

    assert store.latest_canary_run("range-doctor") == {}
    assert list(store.iter_canary_runs("range-doctor")) == []
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM canary_runs").fetchone()[0] == 0


def test_a_canary_is_running_durably_before_external_work_starts(tmp_path: Path):
    store = Store(tmp_path / "running-canary.sqlite3")

    run_id = store.begin_canary_run(
        "range-doctor",
        "https://docket.example",
        started_at="2026-08-15T08:00:00+00:00",
    )

    assert store.latest_canary_run("range-doctor") == {
        "id": run_id,
        "service_id": "range-doctor",
        "target_url": "https://docket.example",
        "started_at": "2026-08-15T08:00:00+00:00",
        "finished_at": None,
        "verdict": "running",
        "checks": [],
    }


def test_a_finished_canary_round_trips_its_structured_evidence(tmp_path: Path):
    store = Store(tmp_path / "finished-canary.sqlite3")
    run_id = store.begin_canary_run("range-doctor", "https://docket.example")

    finished = store.finish_canary_run(
        run_id,
        verdict="passed",
        checks=CANARY_CHECKS,
        finished_at="2026-08-15T08:01:00+00:00",
    )

    assert finished["verdict"] == "passed"
    assert finished["finished_at"] == "2026-08-15T08:01:00+00:00"
    assert finished["checks"] == CANARY_CHECKS
    assert store.latest_canary_run("range-doctor") == finished


@pytest.mark.parametrize("verdict", ("passed", "failed", "not_yet_exercised"))
def test_every_terminal_canary_verdict_is_retained(tmp_path: Path, verdict: str):
    store = Store(tmp_path / f"{verdict}.sqlite3")
    run_id = store.begin_canary_run("range-doctor", "https://docket.example")
    checks = [
        {
            **CANARY_CHECKS[0],
            "status": "passed" if verdict == "passed" else verdict,
        }
    ]

    assert (
        store.finish_canary_run(run_id, verdict=verdict, checks=checks)["verdict"]
        == verdict
    )


def test_a_passed_canary_requires_at_least_one_check_and_every_check_to_pass(
    tmp_path: Path,
):
    store = Store(tmp_path / "pass-validation.sqlite3")
    empty = store.begin_canary_run("range-doctor", "https://docket.example")
    incomplete = store.begin_canary_run("range-doctor", "https://docket.example")

    with pytest.raises(ValueError, match="non-empty"):
        store.finish_canary_run(empty, verdict="passed", checks=[])
    with pytest.raises(ValueError, match="every check"):
        store.finish_canary_run(
            incomplete,
            verdict="passed",
            checks=[{**CANARY_CHECKS[0], "status": "not_yet_exercised"}],
        )

    assert store.latest_canary_run("range-doctor")["verdict"] == "running"


@pytest.mark.parametrize("status", ("running", "green", "skipped", ""))
def test_a_canary_refuses_an_unknown_check_status(tmp_path: Path, status: str):
    store = Store(tmp_path / f"bad-check-{status or 'blank'}.sqlite3")
    run_id = store.begin_canary_run("range-doctor", "https://docket.example")

    with pytest.raises(ValueError, match="check status"):
        store.finish_canary_run(
            run_id,
            verdict="failed",
            checks=[{**CANARY_CHECKS[0], "status": status}],
        )


def test_a_canary_check_must_carry_what_was_checked_observed_and_evidenced(
    tmp_path: Path,
):
    store = Store(tmp_path / "unstructured-check.sqlite3")
    run_id = store.begin_canary_run("range-doctor", "https://docket.example")

    with pytest.raises(ValueError, match="leg, checked, observed and evidence"):
        store.finish_canary_run(
            run_id,
            verdict="failed",
            checks=[{"status": "failed", "checked": "landing page"}],
        )


@pytest.mark.parametrize(
    "sensitive_key",
    (
        "x-payment",
        "payment_signature",
        "authorization",
        "signature",
        "private_key",
        "mnemonic",
        "api_secret",
    ),
)
def test_canary_evidence_refuses_raw_payment_material_and_secrets(
    tmp_path: Path, sensitive_key: str
):
    store = Store(tmp_path / f"sensitive-{sensitive_key}.sqlite3")
    run_id = store.begin_canary_run("range-doctor", "https://docket.example")
    check = {
        **CANARY_CHECKS[0],
        "evidence": {"response": {sensitive_key: "must-not-be-stored"}},
    }

    with pytest.raises(ValueError, match="sensitive"):
        store.finish_canary_run(run_id, verdict="failed", checks=[check])

    assert store.latest_canary_run("range-doctor")["verdict"] == "running"


def test_a_finished_canary_cannot_be_rewritten(tmp_path: Path):
    store = Store(tmp_path / "terminal-canary.sqlite3")
    run_id = store.begin_canary_run("range-doctor", "https://docket.example")
    store.finish_canary_run(run_id, verdict="passed", checks=CANARY_CHECKS)

    with pytest.raises(ValueError, match="running"):
        store.finish_canary_run(run_id, verdict="failed", checks=CANARY_CHECKS)

    assert store.latest_canary_run("range-doctor")["verdict"] == "passed"


def test_canary_history_is_newest_first_and_scoped_to_one_service(tmp_path: Path):
    store = Store(tmp_path / "canary-history.sqlite3")
    first = store.begin_canary_run("range-doctor", "https://docket.example")
    store.finish_canary_run(first, verdict="passed", checks=CANARY_CHECKS)
    second = store.begin_canary_run("range-doctor", "https://docket.example")
    store.begin_canary_run("grid-operator", "https://docket.example")

    assert [row["id"] for row in store.iter_canary_runs("range-doctor")] == [
        second,
        first,
    ]
    assert store.latest_canary_run("range-doctor")["id"] == second


@pytest.mark.parametrize("limit", (0, -1, 101))
def test_canary_history_refuses_an_unbounded_or_non_positive_limit(
    tmp_path: Path, limit: int
):
    store = Store(tmp_path / "canary-limit.sqlite3")

    with pytest.raises(ValueError, match="limit"):
        list(store.iter_canary_runs("range-doctor", limit=limit))
