# Stage 0 — Repair the Evidence Contract

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Fix the three verified integrity bugs in Docket's evidence layer and make snapshots safe to promote automatically, so the rest of Path B can lean on "evidence" as the moat without a TermiX-grade judge catching a denominator or provenance error.

**Why first:** These are smaller than the category build, they protect every later claim, and bug #2 (unfinished-snapshot promotion) becomes *active* the moment Stage 5's refresh loop lands — it must be fixed before, not after.

**Context (all verified against live code/data this session):**
- `docket/coverage.py:46` — `probed = len(observations)` counts blocked + unresolved observations that never made an HTTP request. Live `/stats` publishes `responded_pct_of_probed = 13/35 = 37.143`, but only 14 of those 35 were HTTP-attempted (13 responded + 1 timeout). The label promises a denominator the number doesn't honor.
- `docket/store.py:157` — `latest_snapshot_id` returns `MAX(id)` with no `finished_at` filter. An unfinished snapshot 2 (sampled NULL) exists in `data/agents.sqlite3`. Dormant today (snapshot 3 is the max and is finished) but unsafe under automated refresh.
- `docket/signals.py:37` — `publisher_key` returns `name.split()[0]` for normal names: name-family, not minter provenance. Over-promising label.
- The snapshot row (`store.py` SCHEMA) does not persist the ingestion filter, so `/stats` presents the `min_feedbacks>=1` universe of 506 as "complete 506/506, 100% feedback" without carrying "this population was prefiltered."

## Global Constraints
- No new dependencies. Run with `./.venv/Scripts/python`. Repo `C:\Users\gudma\OneDrive\Desktop\GITHUB-FILES\docket`, branch `feat/stage0-evidence-contract`. Do NOT push, do NOT deploy (Fable 5 reviews first, then a separate guarded deploy).
- These are PUBLIC CONTRACT changes (field renames). The drift test (`llms.txt` must mention every OpenAPI path) and the no-verdict contract test must both stay green. Update `llms.txt`, `skill.md`, and web copy in lockstep with any field rename.
- Every published number keeps its denominator. The fix REPLACES one mislabeled denominator with correctly-labeled ones — it does not hide a number.
- No Claude/Anthropic attribution; no Co-Authored-By. Stage by explicit filename.
- `.gitattributes` forces LF — keep it.

---

### Task 1: Honest liveness denominators

**Files:** `docket/coverage.py`, `docket/api/models.py`, `docket/api/static/llms.txt`, `docket/api/static/SKILL.md`, `docket/api/web/*` (any page showing the probe rate), `tests/test_coverage.py`, `tests/test_web.py`

**The fix:** distinguish, in `coverage_report`, three counts from the observations:
- `endpoints_evaluated` = total observations (was mislabeled `endpoints_probed`)
- `endpoints_attempted` = observations whose outcome is one of {responded, timeout, refused, error} (an HTTP request was actually issued) — NOT blocked, NOT unresolved
- `endpoints_responded` = outcome == responded

Publish BOTH rates, each named for its own denominator:
- `responded_pct_of_attempted` = responded / attempted (e.g. 13/14 = 92.857)
- `responded_pct_of_evaluated` = responded / evaluated (e.g. 13/35 = 37.143)

Remove `responded_pct_of_probed` and `endpoints_probed` entirely (rename, not alias — a wrong label must not survive). `blocked` and `unresolved` stay as their own counts. Update `render_markdown`, the API `StatsResponse` model, `llms.txt`/`SKILL.md` prose, and every web page that prints the old field. Add a test asserting: attempted excludes blocked+unresolved; the two rates use the two denominators; and (regression) neither `endpoints_probed` nor `responded_pct_of_probed` appears in any response, doc, or page.

- [ ] Write the failing test first (pin attempted = evaluated − blocked − unresolved; both rates correct on a seeded snapshot with 13 responded / 1 timeout / 10 blocked / 11 unresolved → attempted 14, of_attempted 92.857, of_evaluated 37.143).
- [ ] Implement in `coverage.py`; propagate the rename through models, docs, web.
- [ ] Full suite green. Commit `fix(coverage): split evaluated vs attempted so no rate divides by un-probed targets`.

### Task 2: Never promote an unfinished snapshot

**Files:** `docket/store.py`, `tests/test_store.py`

**The fix:** add `latest_complete_snapshot_id(chain_id=56)` that returns `MAX(id) WHERE chain_id=? AND finished_at IS NOT NULL AND sampled IS NOT NULL`. Change `create_app`'s default snapshot resolution (`docket/api/routes.py`) to use it. Keep `latest_snapshot_id` for callers that genuinely want the newest row, but the SERVED snapshot must be the newest COMPLETE one. Test: with snapshots {1 finished, 2 unfinished, 3 finished}, complete-resolver returns 3; with {1 finished, 2 unfinished(higher id)}, it returns 1, never 2.

- [ ] Failing test → implement → wire into routes → full suite green.
- [ ] Commit `fix(store): serve only the latest COMPLETE snapshot, never a crashed sweep`.

### Task 3: Persist the population filter

**Files:** `docket/store.py` (SCHEMA + `begin_snapshot`/`ingest_targeted` path), `docket/ingest.py`, `docket/coverage.py`, `docket/api/models.py`, `tests/test_store.py`, `tests/test_ingest.py`

**The fix:** persist the ingestion predicate on the snapshot row — a `population` text column, e.g. `"min_feedbacks>=1"` for targeted sweeps or `"all"` for a full sweep. `ingest_targeted` currently returns `min_feedbacks` transiently (`ingest.py`) but never stores it. Add it to `begin_snapshot`/the snapshot insert, surface it in the `Coverage` model as `population: str`, and render it wherever coverage is shown so `/stats` and the UI state "this universe was filtered to agents with ≥1 feedback" rather than implying a whole-registry census. Migration: existing rows get `population = NULL` → treated/displayed as "unspecified".

- [ ] Failing test (a targeted sweep persists `population="min_feedbacks>=1"`; coverage_report surfaces it) → implement → full suite green.
- [ ] Commit `feat(store): persist the population filter so a coverage number states its universe`.

### Task 4: `publisher` → `name_family` (honest label)

**Files:** `docket/signals.py`, `docket/coverage.py`, `docket/api/models.py`, `docket/api/routes.py` (the `publisher` filter), `docket/api/web/*`, `docket/api/static/llms.txt`, `docket/api/static/SKILL.md`, `tests/*` referencing publisher

**The fix:** rename `publisher_key` → `name_family`, and every output/field/filter/doc string `publisher` → `name_family`, with a one-line docstring stating it groups by the first token of the agent name (or owner for placeholder names) and is NOT verified minter provenance. This is a pure honest-labeling rename; the grouping logic is unchanged. Keep the drift test and no-verdict test green.

- [ ] Rename across code + docs + web + tests → full suite green.
- [ ] Commit `refactor(signals): name_family is a name heuristic, not publisher provenance`.

### Task 5: Human-page denominator disclosure

**Files:** `docket/api/web/index.html` (+ `app.js` if needed), `tests/test_web.py`

**The fix:** the human landing prints "sampled 506 of 506, complete" without stating the 506 is the `≥1 feedback` slice of a 247,278-agent registry. Add, on the human pages that show the snapshot count, a plain-language line naming the registry total and the filter (driven from the persisted `population` + the registry total, not hardcoded). Test that the landing page mentions both the sampled figure and that it is a filtered slice.

- [ ] Failing test → implement → full suite green.
- [ ] Commit `fix(web): state that 506 is the feedback-filtered slice, not the whole registry`.

---

## After all tasks
- Full suite green; `git log` shows five focused commits.
- This branch is REVIEWED BY FABLE 5 before any merge/deploy (partnership rule). Do not deploy from this plan.

## Self-review
- Every change replaces a mislabeled/absent denominator with a correctly-labeled one; none hides a number.
- The renames ripple through the public contract; the drift test and no-verdict test are the guards that they stayed consistent.
- Bug #2's fix lands before Stage 5's refresh loop, as required.
