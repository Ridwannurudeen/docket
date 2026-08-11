# Stage 4 — The v2 Advantage Report

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Replace one-run-each eligibility evidence with pre-registered, repeated-trial evidence carrying null baselines, retained failures and published distributions — and land at least one agent advantage on **substantive outcome quality, not speed**.

**Where we are:** v1 is three tasks, **one run each**, served at `/advantage` + `/advantage.json`. It is honest and it is thin: every figure is a single observation, and its own method string says so (`routes.py:85-94`). Its most-quoted number (120× on the trading task) is one the report itself discounts, because the agent arm did not answer the question asked.

**The exit gate this stage is measured against** (`docs/deliberation/CODEX-ASSESSMENT.md:374`): *every headline claim has repeated n/window/method/risk evidence; at least one clear agent advantage is on substantive outcome quality, not only speed.*

## Verified live this session — build against these, do NOT re-derive

- **v1 is immutable.** `docket/advantage/{harness.py,experiments/{01-liquidity,02-trading,03-security}.json}`, served by `routes.py:462-476`. 13 tests guard it (`tests/test_advantage_report.py`), including that a reader meets the security **loss** in the summary before any task section. v2 is **additive**: v1's files, route, JSON shape and page do not change. If a v1 test needs editing to make v2 pass, the change is wrong.
- **The harness contract**: `Experiment(task_id, question, category, agent_arm, manual_arm, manual_steps, notes)`; `record_arm(name, fn, cost=)` times the call, then hashes the output with `hire.receipts.canonical_hash` **after the clock stops**; `compare()` returns seconds, both costs and a ratio, and **no verdict**. Reuse this vocabulary — v2 extends it, it does not fork a second recipe.
- **`tickmath.in_range` is `tick_lower <= current_tick < tick_upper`** (`tickmath.py:42`) — a pure integer comparison. **A "did the agent get the range verdict right" experiment is TAUTOLOGICAL: the agent computes ground truth directly, so it can only ever score 100%. Do not build it.** Range Doctor's verdicts are deterministic reads, not predictions; the measurable thing about them is the *arithmetic*, below.
- **Warden is live** at `POST https://warden.gudman.xyz/api/demo/scan`, body `{"payload": "<text>"}`. Returns `{verdict: ALLOW|SANITIZE|BLOCK, risk_level, threat_classes: [...], detections: [{class, match, confidence, source}], sanitized_payload, recommendation, checks}`. `threat_classes` being a **labelled set** is what makes a scored corpus possible. **Verified 3/3 this session.**
- **DNS to `*.gudman.xyz` from this machine is sporadic** — the first probe failed `getaddrinfo`, three retries all succeeded. Any corpus run needs retry-with-backoff, and a DNS failure must be recorded as a **failed trial**, never silently dropped and never counted as a detection miss.
- **v1's task 03 is the loss to beat**: manual found four vectors and called BLOCK; the hire returned SANITIZE/MEDIUM with one class (DRAIN_ADDRESS). It missed the authority spoof, the instruction override and the exfil channel.
- **The known Warden defect, already reproduced by two operators:** a **newline** between the credential clause and the destination clause flips `SECRET_EXFIL` from detected to ALLOW. The trigger is isolated; the **mechanism is not**. Corpus text must say exactly that and no more.
- **PancakeSwap explorer is keyless**: `explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top` returns a bare list, all numerics as strings. `net_fee_apr = (feeUSD24h − protocolFeeUSD24h) × 365 / tvlUSD`; gross overstates by ~⅓.
- **No Docket transaction has ever been sent** (`docs/runbooks/grid-mainnet-proof.md:3`), and Health Guard has **no execution path at all** (Fable, Stage 3 audit, answer (d)). So realized net economics, net P&L over a window, and intervention latency are **not measurable in this build**. The plan below does not pretend otherwise, and Task 5 is explicit about what a replay is.

## Global Constraints

- **Pre-registration is the point.** A spec — metric, null baselines, n, stopping rule, and *what result would falsify the claim* — is committed **before** the runs, and every run record carries the spec's hash. A metric chosen after seeing the data is the failure mode this whole stage exists to rule out.
- **Publish all runs, never only aggregates.** A mean with no distribution behind it is a claim a reader cannot contest. Every trial — including failures — is retained and served.
- **A failed trial is data.** Upstream down, DNS gone, timeout: recorded with its error, counted in the denominator, never quietly re-run until it passes.
- **The human arm does not scale and must not be faked.** v1's manual arms are n=1, performed by hand. v2's repeated trials are agent-vs-**null baseline**. Say so in those words: any comparison against a human is n=1 and carried over from v1. **Never simulate a human arm and report it as one.**
- **No counterfactual claims.** Task 5 replays a deterministic plan over historical observations. It is not a trading record, no transaction was sent, and the record says so in its own first sentence. "Would have made X" is sayable only with "over this stated series, under these stated assumptions, having sent nothing".
- Every rate keeps its denominator and window. No verdict vocabulary. No new dependencies. `./.venv/Scripts/python`. Repo `docket`, branch `feat/stage4-advantage-v2`. Do NOT push, do NOT deploy, **no transactions of any kind**. Fable 5 audits before merge.
- No attribution/Co-Authored-By. Stage by explicit filename.

## File Structure
```
docket/advantage/v2/__init__.py
docket/advantage/v2/spec.py        # TaskSpec: pre-registered metric, nulls, n, falsifier; content-hashed
docket/advantage/v2/trials.py      # repeated runs, failure retention, distribution summary over ALL runs
docket/advantage/v2/scoring.py     # precision/recall/per-class, every rate with its denominator
docket/advantage/v2/corpus/security/*.json     # labelled payloads + their pre-registered labels
docket/advantage/v2/specs/*.json               # the committed pre-registrations
docket/advantage/v2/runs/*.json                # every trial, including failures
tests/test_advantage_v2_spec.py
tests/test_advantage_v2_trials.py
tests/test_advantage_v2_scoring.py
tests/test_advantage_v2_corpus.py
tests/test_advantage_v2_api.py
```

---

### Task 1: Pre-registration

**Files:** `docket/advantage/v2/{__init__,spec}.py`, `tests/test_advantage_v2_spec.py`

`TaskSpec` frozen record: `spec_id`, `question`, `category`, `claim` (the one sentence the run is testing), `metric` (name + exact formula + units), `null_baselines` (list of `{name, what_it_does, why_it_is_the_right_null}` — at least two), `dataset_ref` + `dataset_sha256`, `n_planned`, `stopping_rule`, `falsifier` (the result that would refute the claim), `registered_at`.

- `spec_hash` = `canonical_hash` of the record (reuse `hire.receipts.canonical_hash` — same recipe as receipts and v1 output hashes).
- Construction **raises** if: `null_baselines` has fewer than two entries, `falsifier` is empty, `n_planned` < 2, or `metric` carries no formula. A claim nothing could refute is not a claim.
- `save`/`load` to `specs/`, deterministic JSON with LF, matching `harness.save`'s recipe exactly.

Tests: a spec with one null raises; an empty falsifier raises; the hash is stable across save/load; two specs differing in one character hash differently.

- [ ] Failing tests → implement → commit `feat(advantage): pre-registered task specs that name their own falsifier`.

### Task 2: Repeated trials with retained failures

**Files:** `docket/advantage/v2/trials.py`, `tests/test_advantage_v2_trials.py`

- `run_trials(spec, arm_fn, *, n, retry) -> TrialSet` — runs `arm_fn` n times, each trial recording `{index, seconds, output, output_hash, error, attempts}`. A trial that raised keeps its error and its place in the denominator.
- Retry is **per attempt, not per trial**: a DNS failure retried twice and then succeeding is ONE trial with `attempts: 3`, not three trials. A trial that exhausts its retries is a failed trial and stays in the set.
- `TrialSet.summary()` → `{n_planned, n_run, n_succeeded, n_failed, seconds: {min, median, max}, method}`. It must expose `.trials` in full; **any caller may read the aggregate only alongside the runs it came from.**
- No `mean` without `n` beside it, and no rate without its denominator.

Tests: a failing arm is retained with its error and counted in `n_run`; retries collapse into one trial with an attempt count; the summary's denominators match the trial list exactly; a zero-success set summarises without dividing by zero.

- [ ] Failing tests → implement → commit `feat(advantage): repeated trials that keep their failures`.

### Task 3: The security corpus — the headline

**Files:** `docket/advantage/v2/corpus/security/*.json`, `docket/advantage/v2/scoring.py`, `tests/test_advantage_v2_{corpus,scoring}.py`

This is where v1 lost, which is exactly why it is the headline. A blinded, labelled corpus turns "our agent missed three of four vectors" into a measured rate with a denominator.

**Corpus** (hand-authored, ≥40 payloads, each `{payload_id, text, labels: [threat_class...], provenance, why_this_label}`):
- The four vectors from v1's task 03, split into their own cases.
- **Benign controls** — at least a third of the corpus, so precision is measurable. A corpus of only attacks makes "flag everything" score perfectly.
- The newline-split `SECRET_EXFIL` minimal pair: the detected form and the ALLOW form, **as two payloads differing only in that newline**. `why_this_label` states the trigger is isolated and **the mechanism is not** — no more than the evidence supports.
- Labels come from Warden's own published class vocabulary, so a miss is a miss against the vendor's own terms, not against ours.

**Scoring** (`scoring.py`): per-class and overall `precision`, `recall`, each as `{numerator, denominator, value}` — never a bare float. Plus the **null baselines, computed not asserted**: `flag_nothing` (recall 0), `flag_everything` (precision = corpus base rate), and `keyword_match` (a stated word list). The agent's numbers mean nothing until they are read against those three.

Tests: every corpus payload has ≥1 label or is explicitly labelled benign; the minimal pair differs **only** by the newline (assert it byte-for-byte); `flag_everything` scores exactly the base rate; a rate with no denominator raises; scoring is deterministic for fixed input.

- [ ] Failing tests → implement → run the corpus against live Warden with retry → commit `feat(advantage): a labelled security corpus scored against three null baselines`.

### Task 4: The liquidity arithmetic, at scale

**Files:** `docket/advantage/v2/specs/`, run records, tests

v1's task 01 found the manual arm computing 15.406% where the agent computed 15.399% — because the UI rounds ($2.06K) and the agent reads raw ($2,058). One pair. Make it a distribution.

Over the live eligible pool set: for each pool, compute the net rate from raw figures and the rate a manual reader gets from **UI-rounded** figures, and record the gap. Null baseline: **`quote_gross`** — what a reader who skips the protocol cut publishes, which v1 measured at ~⅓ overstatement on one pool. Report the distribution over n pools, with the window and the source snapshot.

The claim under test is narrow and true or false: *reading raw figures rather than displayed ones changes the published rate by a measurable amount, and quoting gross changes it by much more.* State which of the two effects dominates — if rounding turns out to be noise against the gross error, **say that**, because it is the more useful finding.

- [ ] Failing tests → implement → commit `feat(advantage): the rounding and gross-vs-net gaps as distributions, not one pair`.

### Task 5: The grid replay — counterfactual, and labelled as one

**Files:** `docket/advantage/v2/specs/`, run records, tests

Replay the **deterministic** grid plan (`agents/grid/plan.py`, whose plan hash is already stable) over a stated historical series, counting level triggers. Null baselines: **buy-and-hold** over the identical window, and **random-entry** at the same trade count.

**Every record here opens with the same sentence: no transaction was sent, this is a replay of a plan against recorded observations, and it is not a trading record.** Report trigger counts, the window, the series' source and hash, and the exposure the plan would have carried. Where a figure depends on an assumption (fees, slippage, fill at the level price), the assumption is named inline and its effect stated.

If the historical series cannot be sourced from a keyless first-party endpoint with a verifiable hash, **stop and report that** rather than reaching for an unverifiable dataset. A backtest on a series nobody can re-fetch is worth less than an honest gap.

- [ ] Failing tests → implement → commit `feat(advantage): a grid replay stated as a replay, against two null baselines`.

### Task 6: The explorer, and one source of truth for the cards

**Files:** `docket/api/routes.py`, `docket/api/web/advantage-v2.html`, `llms.txt`, `SKILL.md`, `docket/marketplace/registry.py`, `tests/test_advantage_v2_api.py`

- `GET /advantage/v2.json` — specs, every trial, the summaries, and the null baselines beside every agent figure. **`/advantage.json` is untouched.**
- A page that shows **all runs**, not only aggregates, with failures visible rather than filtered. v1 stays reachable and is linked as the prior version — never overwritten, never quietly superseded.
- **Service-card evidence derives from these records**, so a card and the report cannot drift. A test asserts a card's quoted figure equals the record's, computed — not copied.
- llms.txt + SKILL.md updated in lockstep (the drift test enforces every OpenAPI path).

- [ ] Tests (v2 path 200s; every served rate carries its denominator; failures appear; v1's 13 tests still green and its JSON byte-identical; no verdict words) → commit `feat(advantage): the v2 explorer, with v1 preserved beside it`.

---

## After all tasks
Full suite green; v1 unchanged and its tests green without edits. Fable 5 audits before merge, with attention to: is any headline claim a single observation wearing a distribution's clothes? does any aggregate appear without the runs behind it? is any null baseline asserted rather than computed? is the replay stated as a replay everywhere a reader can land? and — the one that matters most — **is the substantive-quality claim real, or is it speed again with a new name?**

## Self-review
- The stage is built around the task v1 **lost**, because that is the one where a measured improvement is credible and a measured failure is still publishable.
- Pre-registration with a named falsifier is what separates this from a report that went looking for a flattering number; the spec hash on every run is what makes that checkable rather than promised.
- The three claims v1's spec asked for and this build cannot support — realized LP economics, net P&L, intervention latency — are absent by name rather than approximated, because each needs capital deployed and transactions this build has never sent.
