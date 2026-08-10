# Fable 5 — Stage 0 code audit (pre-merge)

**Scope:** branch `feat/stage0-evidence-contract`, commits a1f6dde, 281825c, d9514b9, efc387d, 80f23b4 on top of 0629c8a. Audited 2026-08-10 against the plan (`docs/plans/2026-08-12-stage0-evidence-contract.md`), the builder's report (`.superpowers/sdd/stage0/report.md`), and the live `data/agents.sqlite3`.

**Method:** every quantitative claim in the builder's report was independently recomputed — the live database was read only via SQLite `mode=ro`; all app execution (coverage_report, TestClient, uvicorn + a real browser over all three pages) ran against a scratchpad copy. The full suite was run (251 passed), the base commit's suite was collected in a throwaway worktree (225), and the worktree was removed. `git status` is clean; nothing was pushed, deployed, or mutated.

## Verdict: MERGE WITH FIXES

Nothing blocks this branch. All three verified bugs are actually fixed, the fixes are correct on the live data, no number lost its denominator, no verdict word crept in, and the builder's report — checked line by line under the disclosure that its first draft fabricated evidence — is accurate in every figure I could recompute. Two contract-level defects must be fixed before merge because they are the same defect class Stage 0 exists to eliminate, both are wording/guard-level, and both are cheap. F1 and F2 are conditions on the merge, not arguments against it.

---

## Tier 1 — required before merge

### F1 (MEDIUM): `?publisher=` now silently un-filters a documented query

The pre-branch `llms.txt` — the one serving on the public deployment today — documents `publisher` as an `/agents` parameter (base `docket/api/static/llms.txt:81`, `git show 0629c8a`). After this branch, FastAPI drops the unknown name: verified against the live-data copy, `GET /agents?publisher=termix` returns **200, total 506, `coverage.filter: null`** — the whole snapshot where the client asked for a slice. For an evidence product, a filter that silently stops filtering changes the population a client's numbers describe without an error. The builder disclosed this and left it "for review to decide" (report, judgement call 7). Decided: reject it.

The machinery already exists — `invalid_query_parameter` is in the error contract (`llms.txt:250`, handler at `docket/api/routes.py:146-151`) and fires today on bad values (verified: `?limit=abc` → 422). Add a guard in `list_agents` (`docket/api/routes.py:383-391`): if `publisher` is present in `request.query_params`, raise 422 `invalid_query_parameter` with a message naming `name_family` as the successor. Keep it out of the OpenAPI schema.

Fairness note: a contract-compliant client that reads `coverage.filter` back — which llms.txt has always told it to — can detect the miss, and `filter: null` is honest about what ran. That is why this is required-medium, not blocking-high.

### F2 (MEDIUM): `registry_total`'s contract overclaims in two reachable states

The behavior is fine and deliberately pinned; the words promise more than the query delivers.

- **The "never" clause misleads a machine reader.** `llms.txt:63-64` ("Null where no sweep has recorded a total; **never the served snapshot's own figure**"), same sentence at `docket/api/models.py:103-104` and `docket/store.py:206-207`. The intended meaning is "no fabricated fallback in the null case." The plain reading is "registry_total is always an independent, wider measurement" — and the builder's own test pins the opposite: `tests/test_api.py::test_registry_total_equal_to_the_snapshot_means_no_wider_measurement` asserts `registry_total == coverage.expected == 2` when the served snapshot is the only sweep. An agent that believed the sentence would quote a slice against itself thinking it quoted the chain.
- **"Largest chain-wide total" goes false on a targeted-only database.** `registry_total` is `MAX(expected)` over ALL sweeps including filtered ones (`docket/store.py:196-209`), but a filtered sweep's `expected` is the filtered query's total, not a chain-wide one. On a fresh deployment whose sweeps are all `min_feedbacks>=N` — exactly what Stage 5's refresh loop produces on a new database — `/stats` publishes a filtered total under the label "the largest chain-wide agent total any sweep has recorded" (`llms.txt:58-59`), and with two targeted sweeps of different predicates the landing's `paintSlice` (`docket/api/web/app.js:277-284`) prints "That query is a filtered slice of the N agents the registry has reported" where N is itself a filtered total. The live figure (247,146, crashed snapshot 2, verified `expected` recorded at `begin_snapshot` before the crash — `docket/ingest.py:46-56`) is honest today only because snapshots 1–2 happen to be full sweeps whose `expected` dominates the MAX.

Fix is wording, not code, and loses nothing: `MAX(expected)` is a valid **lower bound** on the registry's peak size in every state (every `expected` counts a subset of the registry at some moment). Say that: "the largest agent total any sweep has recorded — at least this many agents exist" in `store.py`/`models.py`/`llms.txt`/`SKILL.md:171-174`, "a registry that has reported **at least** N agents" in `paintSlice` and `render_markdown` (`docket/coverage.py:123-126`), and scope the "never" clause explicitly to the null-fallback case. Optionally, once a full sweep exists with the `population` column recorded, restrict the MAX to `population='all'` and retire the lower-bound hedge.

## Tier 2 — recommended, non-blocking

### F3 (LOW): `paintSlice` branches on a number comparison where `population` is the honest key

`docket/api/web/app.js:277-284`: the census/no-census sentence is chosen by `registry_total > expected`. Two latent wrong sentences: (i) a completed `population="all"` sweep (registry_total == expected) renders "No wider sweep of this chain has been recorded here … is not a census" — denying a census that is one; (ii) `population="all"` with an older, larger `expected` on record (registry shrank) calls the full sweep "a filtered slice." Neither state exists in the live data. When `cov.population` is known, branch on it.

### F4 (LOW): "an HTTP request actually **reached**" overstates for timeout/error outcomes

A timed-out request provably was *issued*; that it *reached* anything is exactly what a timeout fails to prove. The strict verb already used by the markdown ("had a request issued … nothing was ever sent to them", `docket/coverage.py:154-156`) and the landing breakdown ("A request was issued", `docket/api/web/index.html:141`) should win everywhere: `docket/api/models.py:106-107`, `llms.txt:73` ("the ones an HTTP request actually reached"), `llms.txt:357` ("An HTTP request reached 14 of the 35"), `SKILL.md:82` and `:180` ("reached by an HTTP request"), `app.js:329` ("a request reached"). Pedantic, but this project's thesis is that pedantry.

### F5 (LOW): two registry figures in one document, one clause short of reconciled

`llms.txt:283` carries the pre-existing prose "roughly 247,278 registered" (hedged, **not dated in this file** — it will go stale silently) four paragraphs from the new "registry_total: 247,146 … the largest chain-wide total any sweep here has recorded" (`llms.txt:293-297`); the worked example quotes 247,278 again (`llms.txt:366`, `SKILL.md:86`). A hostile judge asks "which is it?" One clause closes it — e.g. "the registry's own count endpoint answered ~247,278 on 2026-08-07; the largest total a Docket sweep has recorded is 247,146" — and dates the prose figure while at it.

## Tier 3 — notes, no action demanded

- **F6:** `latest_complete_snapshot_id` (`docket/store.py:183`) uses "complete" for *ran to its end* (`finished_at`/`sampled` non-null) while the published `complete` field means *sampled == expected*. Live snapshot 1 is "complete" by the resolver and `complete: false` by the field (2,000 of 247,065). Behavior is right — the UI banners partial — but the collision invites a future bug.
- **F7:** the no-backfill stance is asymmetric: `llms.txt:288-291` asserts in prose that snapshot 3's actual filter was `min_feedbacks>=1` while the database refuses to record that same operator knowledge as data. Defensible (prose is an operator claim; rows stay measurement-only) — but it is a choice, and it is what forces F2's MAX over unlabeled rows.
- **F8:** `render_markdown`'s signal table header "| Signal | Agents | Share |" (`docket/coverage.py:128`) never names the Share denominator in the header (it is `sampled`). Pre-existing; no production caller today (grep: tests only).

---

## The assigned questions, answered

**(a) Denominator split — correct and complete?** Yes. `_ATTEMPTED_OUTCOMES = ("responded", *_FAILURE_OUTCOMES)` derives from the failure tuple (`docket/coverage.py:21`), so attempted ≡ evaluated − blocked − unresolved; verified on live data: 14 = 35 − 10 − 11, rates 92.857/37.143 recomputed exactly. The builder's `agents_probed` claim verified: recomputing the retired formula on live data gives **31**, the shipped `agents_attempted` gives **14** — the old figure overstated by 2.2×, as reported. Hunt for further same-defect fields found none: `with_feedback_pct`, `callable_pct`, `share_pct` all divide by `sampled` and carry that denominator where shown (`app.js:307-337`, table caption `app.js:251`); `agents_responded` now reads against `agents_attempted` (`coverage.py:174-177`); `failed` is a subset of attempted and labeled as such; `endpoints_probeable` appears only beside its definition in markdown. The residual wording defect is F4, a verb not a divisor.

**(b) `registry_total` from MAX(expected) incl. the crashed sweep — honest?** The *number* is honest: `expected` is recorded at `begin_snapshot` from the registry's own answer, before any page iteration (`docket/ingest.py:46-56`), so snapshot 2's crash cannot have corrupted it, and the docstrings disclose "finished or not." The *label* is the problem — see F2. The landing's sentence survives scrutiny on today's data and only on today's data.

**(c) In-place migration of production data — intact and safe?** Yes. Read-only inspection: `population` appended as the trailing nullable column (cid 6), all three rows NULL as specified, `PRAGMA integrity_check` ok, row counts intact (agents 2000/101500/506 per snapshot; 78 endpoint rows and 35 liveness rows on snapshot 3 — matching the pre-work numbers in the plan). Backward-safe: the old code inserts by named columns and reads by row name, so an extra trailing nullable column is invisible to an older checkout. The guarded `ALTER TABLE` (`docket/store.py:84-89`) is idempotent. The file is gitignored; working tree clean.

**(d) `?publisher=` silently ignored — acceptable?** No. Required fix F1.

**(e) Renames consistent across code, llms.txt, SKILL.md, OpenAPI, pages?** Yes. The retired tokens (`endpoints_probed`, `responded_pct_of_probed`, `agents_probed`, `publisher_key`, `distinct_publishers`, `top_publishers`) appear nowhere in the package except as negative assertions in tests (grep + `test_the_retired_probed_labels_survive_nowhere_in_the_package`, which scans every `.py/.html/.js/.txt/.md` under `docket/`). `/openapi.json` generated from the branch: zero retired names, all six new names present, no `publisher` parameter. The three surviving "publisher" words in `app.js` (13, 179, 737) are all about who authored a string, exactly as the builder disclosed. Field-name check was done manually as instructed, not via the paths-only drift test.

**(f) The report's quantitative claims, given the fabrication disclosure?** Every one I could recompute is true: 225 tests at 0629c8a (collect-only in a worktree) → 251 passing now (full run, 28.4s); live `/stats` matches the report's JSON byte-for-value (incl. `registry_total: 247146`, `population: null`); 78 endpoint rows over 43 distinct (agent,url) pairs; `?name_family=gembots` total 14; `responded=true` total 13; 421 name families; old-vs-new 31→14; and the three human pages render as described — slice panel, tiles, browse round-trip, agent 129 "Name family: agentsai" / "Population swept: unspecified" / "Complete: yes — against the population above, not the registry" — with **zero console errors**, verified in a real browser against the copy. One inaccuracy found: judgement call 2 says the 247,278 figure is "dated 2026-08-07 and hedged" — it is hedged but **not dated** in `llms.txt`; only `SKILL.md`'s example ties it to the snapshot date (F5).

## Where the plan was wrong — builder's errata, verified

All four hold up:
1. `Coverage.population: str` (plan Task 3) would have 500'd the live API — snapshot 3 serves `population: null`, and a required non-nullable pydantic field fails at serialization. `str | None` was right.
2. The plan missed `agents_probed` — same defect, same function; the builder found and fixed it, and disclosed the scope expansion rather than doing it silently.
3. The plan's file map was off: base `coverage.py` had `responded_pct`; the `responded_pct_of_probed` name existed only at the `StatsResponse` boundary. Both gone.
4. "Keep `latest_snapshot_id` for callers that genuinely want the newest row" — it has no production caller (grep: `routes.py` uses only `latest_complete_snapshot_id`; the old name lives only in `store.py` and its contrast test). Kept per plan instruction, with docstring and test; it is dead code by this repo's own standard until the true-resume follow-up lands. Fine to keep for Stage 5, worth remembering.

## Thesis regression check

None found. No published number lost its denominator (the one retired rate was replaced by two better-labeled ones, both verified); no claim outruns its evidence on the live data (F2/F3 are latent states, flagged above); no verdict word appears in any new copy (`test_ui_uses_no_verdict_language` and the api-contract bans pass; manual read of every new sentence concurs). The new landing disclosure is the fix my strategy audit demanded (FABLE-AUDIT.md, "self-inconsistency a TermiX-grade judge would catch") — it is now the strongest denominator statement on the site.
