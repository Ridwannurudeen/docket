# Docket Phase 1g — Agent Advantage Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce TermiX's required Agent Advantage Report — three real tasks run with an agent hired through Docket and without one, with time, cost, and output quality recorded and the actual outputs attached. It is an **eligibility gate**: no report, no prize, however good the marketplace is.

**Architecture:** Two more services join the catalogue so all three tasks are hireable through Docket today (no on-chain registration needed — "hired through your marketplace" is about Docket's hire flow, not about 8004scan discoverability). An experiment harness records both arms of each task with wall-clock timing and hash-bound outputs, and the result is published as a browsable page rather than a PDF, because TermiX's judges arrive through a browser and their agents through the API.

**Tech Stack:** Existing pins only. No new dependencies.

## Global Constraints

- **The manual arm must be genuine.** A strawman baseline is the single easiest way to lose this bounty — a judge who does the task themselves and finds it takes two minutes will discard the whole report. The without-agent arm uses the tools a competent person would actually reach for (block explorers, the protocol's own UI, public APIs, a calculator), performed properly, and its steps are written down so a reader can repeat them.
- **Report time and out-of-pocket cost separately. Never invent an hourly rate** to manufacture a dollar advantage. Time is measured in seconds; cost is what was actually spent (the service price, API fees, gas). If the honest answer is "the manual arm costs nothing but takes 14 minutes", that is the finding.
- **Quality is shown, not asserted.** Both outputs are attached in full and hash-bound. The report may state factual differences ("the manual arm did not compute the protocol fee split, so its APR is 35.7% against the agent's 23.9%") but must not score itself. A test asserts the report body contains no self-congratulatory verdict words.
- **Every claim carries its evidence.** Each task records: what was asked, the exact agent request and response, the exact manual steps and result, wall-clock for both, cost for both, and the SHA-256 of both outputs.
- **If an agent performs worse on a task, that goes in the report.** An honest loss reported straight is worth more than three manufactured wins — and this project's whole credibility rests on that being true.
- At least one task must come from trading, stock, or security (TermiX's rule). Docket will have two: trading and security.
- Verified live 2026-08-08 (retry through DNS flakiness; first attempt returned HTTP 000 on both, then three consecutive successes): `https://solvent.gudman.xyz/signal` → HTTP 200 in ~1.0s; `https://warden.gudman.xyz/health` → HTTP 200 in ~0.6s.
- No Claude/Anthropic attribution; no Co-Authored-By. Stage by explicit filename. Do not push.
- Repo `.`, run with `./.venv/Scripts/python`.

## File Structure

```
docket/hire/catalogue.py       # MODIFY: add solvent-signal and warden-scan
docket/advantage/__init__.py
docket/advantage/harness.py    # records an experiment: both arms, timing, hashes
docket/advantage/experiments/  # the three recorded runs, committed as JSON
docket/api/web/advantage.html  # the published report
tests/test_advantage_harness.py
tests/test_advantage_report.py
```

---

### Task 1: Two more hireable services

**Files:** Modify `docket/hire/catalogue.py`; create `tests/test_catalogue_services.py`

**Interfaces:** `SERVICES` gains `solvent-signal` and `warden-scan`, each a `Service` whose `run` proxies to the live endpoint above.

- `solvent-signal` — input `{}` (no arguments). Returns SOLVENT's latest daily regime signal: the verifiable payload whose `signal_hash` binds to its latest receipt, chain head, and anchor. `what_you_get` must state plainly that this is a regime read with an on-chain-anchored provenance chain, and that a regime read is not a trade recommendation.
- `warden-scan` — input `{"payload": "<untrusted text>"}`. Returns Warden's verdict (ALLOW / SANITIZE / BLOCK) and threat classification for a piece of untrusted text. `what_you_get` must state that the free hosted path is best-effort telemetry rather than an enforcement boundary — Warden's own README says so, and repeating its honest limitation is more credible than hiding it.

- [ ] **Step 1: Write `tests/test_catalogue_services.py`** — assert all three services exist; each declares a non-empty `what_you_get`, an `input_schema`, a price and an asset; `solvent-signal` takes no required input while `warden-scan` requires `payload`; and the existing "no service promises an outcome" ban still passes across all three (add `advice`, `signal to trade`, `will` to the banned list for these two, since a trading signal is the easiest place to over-promise).

- [ ] **Step 2: Implement.** Each `run` uses `httpx` with a timeout and one retry (DNS here is verifiably flaky — the first live check of both hosts returned HTTP 000 before three clean successes). On upstream failure, raise so the hire path returns its structured error rather than a half-result; a hire that silently returns nothing is worse than one that fails loudly.

- [ ] **Step 3: Run** the suite → 166 passed (162 + 4).

- [ ] **Step 4: Commit** `git commit -m "feat(hire): offer SOLVENT regime signal and Warden payload scan"`

---

### Task 2: The experiment harness

**Files:** Create `docket/advantage/__init__.py`, `docket/advantage/harness.py`, `tests/test_advantage_harness.py`

**Interfaces:** `record_arm(name, fn) -> dict` (runs `fn`, times it, hashes the result); `Experiment` dataclass with `task_id`, `question`, `category`, `agent_arm`, `manual_arm`, `manual_steps: list[str]`, `notes`; `save(experiment, path)` / `load(path)`; `compare(experiment) -> dict` producing the factual deltas (`seconds_agent`, `seconds_manual`, `cost_agent`, `cost_manual`, `speedup`) with **no quality judgement**.

- [ ] **Step 1: Write `tests/test_advantage_harness.py`** covering: `record_arm` captures wall-clock seconds and a `0x…` output hash matching `canonical_hash`; a failing arm records the exception rather than raising, so a lost arm is still reported; `compare` computes `speedup` as `seconds_manual / seconds_agent` and returns `None` when either is missing rather than inventing a number; `compare` emits no key whose name or value implies a quality verdict; and a saved experiment round-trips through `load` byte-identically.

- [ ] **Step 2: Implement.** Reuse `docket.hire.receipts.canonical_hash` — the report's hashes must be recomputable the same way a hire receipt's are. Timing uses `time.monotonic()`. Store `cost` as an explicit `{"amount": str, "unit": str, "note": str}` so "0.01 $U" and "0 (public endpoints only)" are both expressible without a fake dollar conversion.

- [ ] **Step 3: Run** → 172 passed.

- [ ] **Step 4: Commit** `git commit -m "feat(advantage): experiment harness recording both arms with hashes"`

---

### Task 3: Run the three experiments for real

**Files:** Create `docket/advantage/experiments/{01-liquidity,02-trading,03-security}.json`

Each experiment is run live and committed verbatim. **Do the manual arm honestly and time it truthfully** — including the parts that are slow because they are genuinely fiddly, and excluding nothing that would make the agent look better.

- [ ] **Task 01 — liquidity (category: yield/LP).** Question: *"Is wallet 0x451871A1753903FB8fdd64a6B838E95aB8D5B80f earning fees on its PancakeSwap v3 positions right now, and if not, why not?"*
  - **Agent arm:** `POST /hire/range-doctor` with that wallet.
  - **Manual arm:** find the wallet's position NFTs (BscScan token holdings), open the position on PancakeSwap's own UI, read the range and current price, then compute the pool's net fee APR by hand from the explorer's pool page — including the protocol-fee subtraction. Record every step and its time.
  - Expected honest finding: the agent's edge is the fee-split arithmetic and doing it across 14 positions rather than one. Whatever the real numbers say, report them.

- [ ] **Task 02 — trading (category: trading, one of TermiX's high-stakes categories).** Question: *"What market regime does SOLVENT read right now, and can I verify that read was not written after the fact?"*
  - **Agent arm:** `POST /hire/solvent-signal`.
  - **Manual arm:** fetch Fear & Greed and funding yourself, apply the same documented rules, and then attempt to establish provenance — pull `/verify`, recompute the receipt chain with `verify_receipts.py`, and check the head against the on-chain anchor. Time it.
  - The interesting axis here is **not** speed, it is verifiability: the manual arm can produce a regime read quickly but cannot cheaply prove the read predates the outcome. Say that plainly, including where the agent's provenance stops (receipts after the last daily anchor are recompute-consistent but not yet on-chain-bound).

- [ ] **Task 03 — security (category: security, TermiX's other high-stakes category).** Question: *"Does this untrusted text contain a prompt-injection or exfiltration attempt, and which class?"*
  - **Agent arm:** `POST /hire/warden-scan` with a real multi-vector payload.
  - **Manual arm:** read the payload and classify it by eye, then verify by checking it against the published corpus categories. Time it, and be honest about how long careful manual review of a single payload actually takes.
  - Use a payload with at least one *non-obvious* vector (e.g. an upper-cased `0X` address prefix, or a vendor token behind a custom header) so the comparison is not trivially won by either side.

- [ ] **Step 4:** After all three, verify each committed JSON: outputs present in full, both hashes recomputable, timings non-zero, and the manual steps written clearly enough that a judge could repeat them.

- [ ] **Step 5: Commit** `git commit -m "docs(advantage): three recorded experiments, both arms"`

---

### Task 4: Publish the report

**Files:** Create `docket/api/web/advantage.html`; modify `docket/api/routes.py`, `docket/api/static/llms.txt`, `docket/api/static/SKILL.md`, `tests/test_advantage_report.py`

- [ ] **Step 1:** Serve `GET /advantage` (HTML) and `GET /advantage.json` (the three experiments as data, so an evaluator's agent can read the report too — the same two-front-doors principle as the rest of Docket).
- [ ] **Step 2:** The page renders, per task: the question, the category, both arms side by side with their timings and costs, the full outputs (in `<pre>`, wrapped with the existing `.wrap-anywhere` utility), the factual deltas, and the manual steps as a numbered list. A standing note at the top states the method: what was measured, what was not, and that no quality score is assigned.
- [ ] **Step 3:** Tests: `/advantage` returns 200 HTML and mentions all three task ids; `/advantage.json` returns all three experiments with both arms populated; the page contains no verdict words (`best`, `superior`, `proves`, `guaranteed`); and — the drift guard — `llms.txt` documents both new paths, since the existing test requires every OpenAPI path to appear there.
- [ ] **Step 4: Run** the suite → ~178 passed.
- [ ] **Step 5: Commit** `git commit -m "feat(advantage): publish the agent advantage report as page and data"`

---

## Self-review (done at write time)

- Spec coverage: this closes TermiX's eligibility gate (3 tasks, both arms, time/cost/quality, outputs attached, ≥1 high-stakes category — Docket has two) and feeds the 30% "proven agent advantage" criterion directly.
- The largest risk is a strawman manual arm, so it is addressed first in the constraints and again per task, with the instruction to report an honest loss if one occurs.
- Cost is deliberately not monetised into a single figure; inventing an hourly rate is the most common way these reports become unfalsifiable.
- Publishing as both page and JSON follows the two-front-doors principle established in Phase 1c — the judges' agents can read the report without a browser.
