# Stage 1 — Unify Discovery, Evidence, and Activation

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Turn Docket from two disconnected systems — a registry explorer and a hard-coded service catalogue — into one marketplace where a person lands on BNB's four job categories, inspects a service's evidence, and reaches a real activation control without instructions.

**Why now:** Both independent audits found the same split-brain. `Service` (catalogue.py:53-65) has no `agent_id`, no category, no evidence link. `AgentSummary` (models.py:53-68) has no category and no hire path. A user who finds an ERC-8004 agent cannot hire it; a user who hires a Docket service cannot inspect its on-chain identity. This stage is the seam, and it scores BNB Functionality and TermiX marketplace-quality (20%) simultaneously.

**Architecture:** A new `docket/marketplace/` package holding the service ontology, joined to the existing raw registry API. `/agents` stays exactly as it is (the fact plane). `/services` is the curated, category-first layer built on top. The web home becomes category-first; the raw 506-row browser moves to a research route.

## Global Constraints
- No new dependencies. `./.venv/Scripts/python`. Repo `docket`, branch `feat/stage1-marketplace`. Do NOT push, do NOT deploy — Fable 5 audits first.
- **The no-verdict contract still binds the fact plane.** A service may state what it does, its price, its declared inputs, and its OBSERVED evidence. It may not carry `best`, `safe`, `trusted`, `recommended`, `score`, or `rank`. Default ordering is recency or name — never a Docket-invented ranking. "Matches the constraints you entered" is legitimate; "Docket recommends" is not. The existing contract test must stay green and must be extended to the new models.
- **Every metric on a service card keeps its denominator and window**, in the Stage 0 style: `{value or numerator/denominator, unit, window, observed_at, method}`. No bare rates.
- **Do not invent category membership.** A service's category is declared by us for services we own, and must be stated as our declaration, not as a measured property of the agent. For third-party registry agents, there is no category data — do not guess one. (Verified: the four BNB categories are near-absent in the indexed 506 — rebalancing 0, grid 1, yield 3, health 0–4. Empty shelves are Stage 3's job to stock, not Stage 1's to fake.)
- **Honest empty states.** A category with no service yet says exactly that and why. Never a "coming soon" that implies imminent stock, never a placeholder card.
- Existing drift test (llms.txt mentions every OpenAPI path) and no-verdict test stay green. Update `llms.txt`/`SKILL.md` in lockstep with new paths.
- No Claude/Anthropic attribution; no Co-Authored-By. Stage by explicit filename. `.gitattributes` LF stays.

## File Structure
```
docket/marketplace/__init__.py
docket/marketplace/models.py      # Category, ServiceRecord, EvidenceRef, Metric
docket/marketplace/registry.py    # the joined service catalogue (services + identity + evidence)
docket/api/models.py              # MODIFY: ServiceCard, ServiceDetail, CategoryListing
docket/api/routes.py              # MODIFY: /services, /services/{id}, /categories
docket/api/web/index.html         # MODIFY: category-first home
docket/api/web/service.html       # NEW: service detail + activation entry
docket/api/web/research.html      # NEW: the raw registry browser (moved from browse)
tests/test_marketplace.py
tests/test_services_api.py
tests/test_web_categories.py
```

---

### Task 1: The ontology

**Files:** create `docket/marketplace/{__init__,models,registry}.py`, `tests/test_marketplace.py`

**Interfaces:**
- `Category` — an enum/frozen set of exactly BNB's four: `rebalancing`, `grid_trading`, `yield_optimisation`, `health_factor`. Each with a plain-language job label ("Keep LP earning", "Run a capped grid", "Move idle liquidity", "Protect a loan") and a one-line description of what an agent in it does.
- `Metric` — `{name, value, numerator, denominator, unit, window, observed_at, method}`; renders as text that always carries its denominator. A `Metric` with a bare value and no denominator is allowed ONLY for counts, never for rates (enforce in `__post_init__`).
- `EvidenceRef` — `{kind, url, label}` pointing at existing truth: an advantage-report task, a liveness observation, an on-chain identity.
- `ServiceRecord` — joins the two worlds: `service_id`, `category`, `agent_id | None` (BSC ERC-8004 identity when bound), `registration_uri | None`, `name`, `what_you_get`, `input_schema`, `price_display`, `price_atomic`, `asset`, `typical_seconds`, `activation` (`one_shot` | `monitor` | `policy_action`), `metrics: list[Metric]`, `evidence: list[EvidenceRef]`, `limitations: str`.
- `SERVICES: dict[str, ServiceRecord]` built from the existing `docket.hire.catalogue.SERVICES` — do not duplicate the run functions; the marketplace record REFERENCES the hire service.

**Honesty requirements with tests:**
- A `ServiceRecord` with `agent_id=None` must render as "no BSC identity bound yet" — never implied to be on-chain. Test it.
- `limitations` is REQUIRED and non-empty for every service. Test it.
- No banned verdict word may appear in any field of any ServiceRecord. Test it against the existing `BANNED_FIELD_NAMES` plus value-level scanning.
- A rate Metric without a denominator raises. Test it.

- [ ] Failing tests → implement → full suite green → commit `feat(marketplace): service ontology joining identity, category and evidence`.

### Task 2: The API

**Files:** modify `docket/api/models.py`, `docket/api/routes.py`; create `tests/test_services_api.py`; update `llms.txt`, `SKILL.md`

**Endpoints:**
- `GET /categories` — the four categories, each with its job label, description, and `service_count` (honest zero where empty).
- `GET /services?category=` — service cards; `total` after filtering; unknown category → 422 `invalid_query_parameter` naming the four valid values (the Stage 0 pattern).
- `GET /services/{service_id}` — full record: what it does, price, inputs, metrics with denominators, evidence links, limitations, activation mode, and the bound identity or an explicit statement that none is bound. 404 `service_not_found` otherwise.

`/agents` and `/agents/{id}` are UNCHANGED — the raw fact API stays exactly as it is. Add a cross-link: `/services/{id}` includes the `agent_id` when bound so a reader can jump to `/agents/{agent_id}`, and nothing more.

- [ ] Failing tests (including: unknown category 422s; a service with no identity says so; every rate in the response carries a denominator) → implement → update llms.txt + SKILL.md for the three new paths (drift test enforces) → full suite green → commit `feat(api): category-first services layer over the raw registry`.

### Task 3: The human journey

**Files:** modify `docket/api/web/index.html`, `app.js`, `style.css`; create `service.html`, `research.html`; modify routes to serve them; `tests/test_web_categories.py`

**The journey BNB's rubric asks for:** land → find by category → understand → activate, with no prior knowledge and no dead end.

- **Home becomes category-first.** Four job cards in plain language ("Keep LP earning", "Run a capped grid", "Move idle liquidity", "Protect a loan"), each showing how many services it has. The coverage/evidence figures stay on the page but move BELOW the jobs — the evidence is the warranty, not the pitch. Keep the Stage 0 filtered-slice disclosure.
- **Category → service cards** with, per card: what you get, price, typical time, its metrics WITH denominators, and a "Hire" control.
- **`service.html`** — the detail: full description, input form driven by `input_schema`, a Run control that calls `POST /hire/{id}` same-origin, the result rendered, the receipt shown with its hashes, and the limitations stated plainly. This is the activation control that does not exist today.
- **`research.html`** — the existing raw 506-row browser, moved. Linked from the nav as "Research the registry". Nothing about it changes except its route and framing.
- Nav on every page gains the categories and the research link.

**Copy discipline (from the audits):** the headline shifts from indictment to warranty — lead with what the reader can *do*, with the evidence as the guarantee beneath it. Do not delete a single denominator or honesty line in the process. A test greps the new pages for banned verdict words, exactly as `test_web.py` does today.

- [ ] Failing tests (each new page 200s and is text/html; home mentions all four categories; a category with zero services renders an honest empty state; no verdict words; no external requests) → implement → full suite green → commit `feat(web): category-first home, service detail with activation, research route`.

### Task 4: Bind our own services

**Files:** modify `docket/marketplace/registry.py`, tests

Give each of the three existing services its honest record:
- `range-doctor` → category `rebalancing` (LP range management is its literal subject), activation `one_shot`, evidence → advantage task 01, limitations → v3-only, read-only, stale `tokensOwed`, ticks not prices.
- `warden-scan` → no BNB category (it is a security service, not one of the four). It must still appear in the marketplace as an uncategorised service rather than be hidden or forced into a category it does not belong to. Evidence → advantage task 03 INCLUDING the loss.
- `solvent-signal` → no BNB category. Evidence → advantage task 02; limitations → historical, halted since 2026-06-29, provenance-only.
- `agent_id`: `solvent-signal` binds to `56:0x8004A169…:136384`. The other two have NO on-chain identity yet — they must render as unbound, not fudged. (Stage 3/5 registers them.)

This is the honest starting inventory: **one of four categories stocked.** The empty states will say so. Stage 3 fills the rest.

- [ ] Tests asserting the bindings and that unbound services say so → full suite green → commit `feat(marketplace): bind the three live services to records, categories and evidence`.

---

## After all tasks
- Full suite green. Fable 5 audits the branch before merge (partnership rule). Do not deploy from this plan.

## Self-review
- The split-brain closes without touching the fact plane: `/agents` is byte-identical in behavior.
- Empty categories are a feature of honesty here, not a gap to paper over — Stage 3 stocks them, and shipping a four-category UI over empty shelves was explicitly named as scoring worse than an honest narrow scope.
- Every new surface inherits the Stage 0 denominator discipline and the no-verdict contract, both test-enforced.
