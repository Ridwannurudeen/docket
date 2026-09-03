# Marketplace pivot — Sep 3 to Sep 9

> **Status:** ACTIVE. Owner directive 2026-09-03: ship the full external audit; Opus 5 builds every
> lane in parallel; Fable 5.1 audits every lane; no approval gates except the final form filing.
> This file is the contract between lanes. A lane that needs something not written here asks the
> supervisor; it does not invent a second contract.

## Goal

By 2026-09-09 Docket is the evidence-backed control plane for BSC financial agents: a user lands,
picks a goal, compares agents, sees price and permissions, activates from the browser, receives a
result and a receipt, and can pause or revoke. All four official categories perform their verb
("Manages LP ranges, resets positions automatically", "Places and manages automated grid orders",
"Routes liquidity to the highest available APR", "Protects lending positions from liquidation")
through one shared bounded-session architecture. The evidence system stays and moves below the
product.

## Verified constraints every lane inherits (2026-09-03)

- `main` = `967f89a`, protected: PR + CI (`test (3.11)`, `test (3.12)`, `package`) only.
- One closure-based factory: `create_app(db_path, snapshot_id, facilitator)` in
  `docket/api/routes.py:687`. No `APIRouter` exists yet. New lanes add an `APIRouter` in their own
  module and register it with ONE `app.include_router(...)` line inside `create_app`, placed
  directly above `app.mount("/static", ...)` (`routes.py:2653`). Routers receive `store` and the
  helpers they need through a small context object built in `create_app`; they never import
  `create_app` internals.
- Persistence is `docket/store.py` `Store` over stdlib `sqlite3`. **DELETE journal mode is
  enforced (`store.py:228-243`); WAL is refused.** New tables go into `SCHEMA` (`store.py:37`) with
  `CREATE TABLE IF NOT EXISTS`; new columns on existing tables go into the in-place migration at
  `store.py:186-227`. DB path comes from `DOCKET_DB` (`routes.py:699`); production is
  `/var/lib/docket/data/agents.sqlite3`.
- Frontend: nine server-rendered HTML pages in `docket/api/web/`, one ES module `app.js`
  (no bundler, no `package.json`, no third-party JS), one `style.css` linked as
  `/static/style.css?v=12`. `index.html` carries NO script tag today. Pages that need JS load
  `<script type="module" src="/static/app.js?v=12">` and dispatch on `document.body.dataset.page`
  (`app.js:2281-2292`). New JS goes in `docket/api/web/js/<module>.js` as ES modules, served under
  `/static/js/...` by the existing mount; keep every existing page working.
- Release smoke (`deploy/release.sh:1061-1172`) pins: `/stats` keys; `/services` rows and the exact
  id set `{grid-operator, health-guard, range-doctor, solvent-signal, warden-scan, yield-router}`
  with `total == 6`; `/categories` exact set; `/advantage/v3.json` exact family-to-state map
  (7 families); `/` contains `<title>Docket`; `/static/style.css` contains `:root {`. **A lane that
  changes any of these updates `release.sh` in the same change**, or the release rolls back.
- Unit tripwire: `deploy/systemd/` has 15 files; `release.sh:496-521` and `preflight.sh:58-74`
  list them; `tests/test_release_scripts.py:378` asserts `len(expected) == 15`, and
  `docs/deployment-runbook.md` must say "all fifteen tracked unit" exactly twice. Lanes adding
  units update all four places consciously (never delete the assertion).
- Payment rail (`docket/hire/x402.py`): x402 v2, scheme `exact`, network `eip155:56`, asset USDT
  `0x55d398326f99059fF775485246999027B3197955`, price `5*10**17` (0.50 USDT), payTo
  `0xe55816904796341bf8535e25f6c8b647927fc946`. `X-PAYMENT` is base64 JSON
  `{x402Version, resource, accepted, payload:{authorization:{token,from,to,value,validAfter,
  validBefore,nonce}, signature}}`; the signature is EIP-712 `TransferWithAuthorization` under the
  domain `{name:"B402", version:"1", chainId:56, verifyingContract:
  0xE1Af7DaEa624bA3B5073f24A6Ea5531434D82d88}` (the B402 RelayerV3, not the token). Settlement
  pulls via ERC-20 allowance, so the payer needs `USDT.allowance(payer, relayer) >= amount`
  (`x402.py:495,566-570`). **Exact-amount approvals only, never unlimited.** The paid path opens
  only when `payment_header_present and (paid_stock or canary_authorized)` (`routes.py:2205`).
- Signing exists: `eth_account` (`Account.from_key`, `sign_transaction`, `encode_typed_data`) is
  a pinned dependency; `eth_sendRawTransaction` is already used at `docket/escrow/settle.py:159`.
  The shared RPC wrapper is `docket/escrow/chain.py::Rpc` (failover over
  `docket/escrow/constants.py:48-53`).
- Calldata builders that already exist: PancakeSwap V2 `swapExactTokensForTokens`
  (`docket/execution/simulate.py:67`, router `0x10ED43C718714eb63d5aA57B78B54704E256024E`);
  Venus `repayBorrow`/`mint` (`docket/agents/venus/guard.py:182-186`); Yield `MoveAction`
  (`docket/agents/yield_router/router.py:283`, one swap leg, LP-add NOT built); Range Doctor emits
  text actions only. NonfungiblePositionManager `0x46A15B0b27311cedF172AB29E4f4766fbE7F4364`,
  v3 factory `0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865`, MasterChefV3
  `0x556B9306565093C855AEA9AE92A594704c2Cd59e` (`positions.py:97-99`). Venus Unitroller
  `0xfD36E2c2a6789Db23113685031d7F16329158384` (`markets.py:51`); Venus publishes no health
  factor, Docket derives `collateral_ratio` (`guard.py:325-345`).
- Registry: 8004scan API client `docket/scan8004.py` (`https://8004scan.io/api/v1`, 0.4 s pacing,
  `list_agents`, `get_agent`); on-chain IdentityRegistry `0x8004A169FB4a3325136EB29fA0ceB6D2e539a432`
  with `tokenURI`/`ownerOf` in `docket/identity/register.py:28,53-70`. Docket's own identities are
  311253/311255/311257/311259, owner `0xe55816904796341bf8535e25f6c8b647927fc946`.
- Tests: no `conftest.py`; each module builds `TestClient(create_app(db_path, ...))` with
  `tmp_path` (pattern `tests/test_api.py:33-64`). A fake facilitator goes in through the third
  `create_app` argument (`tests/test_hire_api.py:127`).
- No new Python dependencies without the supervisor's sign-off. Playwright is allowed for
  `tests/e2e/` only (Node side), never as a runtime dependency. `ruff` and `pip-audit` may be
  added as dev tools by Lane G only.

## Test taxonomy — what a builder may change

**Evidence-integrity tests: never weaken, never delete, fix the prose or the code instead.**
`tests/test_claims_to_evidence.py` (settlement-canary phrases, v3-04 no-advantage rule, file
SHA-256 citations, the "V3 has exactly seven stage-one specifications:" literal which only Lane F
may change together with the spec count), `tests/test_judge_facing_state.py` (the exact
artifact-derived v3 sentence in six docs; the `| Repository visibility | Public (verified
YYYY-MM-DD) |` row), `tests/test_decision_impact.py` (README numbers must equal
`decision_impact_section()`), `tests/test_web_w43.py::test_decision_impact_copy_matches_the_report_rounding_and_denominators`,
`::test_adverse_case_is_not_softened_into_a_scored_verdict`,
`::test_range_receipt_keeps_the_digest_and_reproduction_bound_together`,
`tests/test_advantage_report.py::test_the_page_reaches_no_verdict` (no best/superior/proves/guaranteed),
`tests/test_web.py::test_no_registry_figure_is_typed_into_a_page`, `::test_no_emoji_used_as_iconography`,
the two critical-CSS tests, `tests/test_publication_checklist.py` (no Windows user paths in docs),
`tests/test_advantage_v3_api.py` (llms.txt/SKILL.md must keep naming both v3 routes and every
state; the historical literal "committed v3 artifacts contain 6 families" stays in llms.txt),
`tests/test_release_scripts.py` (update counts consciously, never delete).

**Copy-pinning tests: update them to the new approved copy in the same change, keeping the
assertion style.** `tests/test_web_w43.py::test_hero_uses_the_approved_copy_and_keeps_both_actions_above_the_truth_rail`,
`::test_public_case_file_has_the_fixed_section_order_and_labelled_sections`,
`::test_case_file_stays_restrained_and_uses_the_agreed_tokens` (the word `dashboard` and gradients
stay forbidden; the token list may grow), `tests/test_web_w6.py::test_navigation_names_public_case_file_destinations`,
`tests/test_web_w40.py::test_navigation_and_generated_evidence_use_one_presentation_vocabulary`,
`tests/test_web_categories.py::test_the_home_leads_with_a_marketplace_and_publishes_the_loss_immediately`,
`::test_the_home_names_the_json_behind_it_when_scripting_is_off`,
`::test_yield_service_copy_names_both_current_registered_families`. Lane A owns these updates;
Lanes C and G build new pages to the nav contract below so Lane A's nav test passes on them.

## Site chrome contract (all lanes)

Every HTML page, including `index.html`, carries exactly this primary nav, in this order:

```
<nav class="site-nav" aria-label="Primary">
  <a href="/">Explore</a>
  <a href="/search">Find agents</a>
  <a href="/my-agents">My agents</a>
  <a href="/providers">Providers</a>
  <a href="/advantage">Evidence</a>
  <a href="/llms.txt">API</a>
</nav>
```

Footer keeps `<a href="/pancake">PancakeSwap</a>` and `<a href="/research">Browse agents</a>`
(existing tests pin them) and adds `<a href="/status">Status</a>`. Cache-busting query for CSS
and JS becomes `?v=13` on every page. Colour tokens, type and spacing stay as in `style.css`
(`--bg: #f4f1e8`, no gradients, no emoji iconography, no "dashboard" wording).

## Working rules for every builder

1. Work in your own worktree on branch `build/pivot-<lane>`. Create it at the start:
   `git checkout -b build/pivot-<lane>`. Commit at the end with a plain message and NO
   attribution trailers (no Co-Authored-By, no tool names). Print the commit SHA in your report.
2. Create a venv in the worktree: `python -m venv .venv` then
   `.venv/Scripts/python -m pip install -e ".[dev]"`. Run tests with
   `.venv/Scripts/python -m pytest -q`. The full suite must be green (the main checkout's 6 known
   failures come from an untracked ledger that your worktree does not have).
3. Never touch the VPS (`75.119.153.252`), never deploy, never spend, never push. Never modify
   anything under `docket/advantage/v3/{specs,sources,inputs,runs,calibration-captures,sheets,
   mappings}` unless your lane says so explicitly.
4. Touch only the files your lane owns. Shared touchpoints (`routes.py` router registration,
   `release.sh` arrays, `style.css`) get the smallest possible insert at the place named here so
   merges stay trivial. `style.css` is append-only for every lane except Lane A.
5. Everything you build must work end to end. No stubs, no TODOs, no placeholder pages. If a
   part cannot be completed, finish everything else and say exactly what is missing and why in
   `BUILD-REPORT.md` at the worktree root (untracked; do not commit it).
6. Every published number carries its numerator, denominator, window and method. Never hard-code
   an operational count in HTML or Markdown; derive it.
7. Match the existing style: stdlib plus the pinned dependencies, dataclasses, explicit errors,
   escaped HTML, the same restrained prose voice. Read the neighbouring code before writing.

## Shared contracts

### Activation / job model (`docket/jobs/models.py`; Lane B owns the code, all lanes use the shape)

```
Activation:
  activation_id: str          # "act_" + 24 hex; ordering by created_at
  service_id: str             # catalogue id (range-doctor, grid-operator, yield-router, health-guard, ...)
  category: str               # rebalancing | grid_trading | yield_optimisation | health_factor
  kind: "one_shot" | "persistent"
  owner: str                  # checksummed EOA that created it (proved by EIP-191 signature)
  state: see below
  quote: {asset, amount_atomic, amount_display, pay_to, payment_scheme: "x402-exact" | "free_tier"}
  policy: SessionPolicy | null
  session: {address, funded_atomic: {token: amount}, spent_atomic: {token: amount}} | null
  inputs: dict                # the service request body
  result: dict | null
  receipts: [Receipt]         # every action; hire receipts reuse docket.hire.receipts.build_receipt
  events: [{at, from_state, to_state, reason, actor: "user"|"docket"|"chain"}]
  next_action: {kind: "connect_wallet"|"approve_token"|"sign_payment"|"fund_session"|
                "approve_nft"|"sign_transaction"|"wait"|"none", detail: dict}
  auth_nonce: str             # single-use, rotated after every accepted mutation
  created_at, updated_at, expires_at
States (one_shot):   quoted -> awaiting_wallet -> authorized -> paid_or_reserved -> queued ->
                     running -> needs_approval -> completed | failed | refunded
States (persistent): quoted -> awaiting_wallet -> authorized -> funded -> active
                     -> paused -> active | revoked | expired   (needs_approval may occur from active)
```

Transitions append to `events`; illegal transitions raise `IllegalTransition`. Store table
`activations` (JSON columns for policy/session/inputs/result/receipts/events; indexed `owner`,
`service_id`, `state`, `created_at`).

### Activation API (Lane B implements; Lane C consumes)

```
GET  /api/activations/nonce?owner=0x..     -> {nonce, message}
POST /api/activations                      {service_id, kind, owner, owner_signature, nonce, inputs, policy?}
                                           -> 201 Activation
GET  /api/activations/{id}                 -> Activation
GET  /api/activations?owner=0x..           -> {activations: [...], total}
GET  /api/activations/{id}/prepared        -> {calls: [PreparedCall]}     # what the browser signs next
POST /api/activations/{id}/approve         {owner_signature, nonce, tx_hash? , payment_header?}
POST /api/activations/{id}/pause           {owner_signature, nonce}
POST /api/activations/{id}/cancel          {owner_signature, nonce}
POST /api/activations/{id}/revoke          {owner_signature, nonce}      # sweeps the session back
GET  /api/marketplace/summary              -> see Lane A
GET  /api/status                           -> see Lane G
```

Owner auth: every mutating call carries `nonce` (the activation's current `auth_nonce`, or for
create the value from `/api/activations/nonce`) and `owner_signature` = EIP-191 `personal_sign`
of the exact `message` string the server issued: `"Docket activation {id} {action} {nonce}"`
(`"Docket activation create {service_id} {nonce}"` for create). The server recovers with
`Account.recover_message` and compares to `owner`. Errors are JSON `{error_code, message}` with
the codes `bad_signature`, `stale_nonce`, `illegal_transition`, `not_owner`, `policy_violation`,
`simulation_failed`, `expired`.

### PreparedCall (what the browser signs, or what a session executes)

```
{to, data, value_atomic, chain_id: 56, gas_ceiling, deadline, purpose,
 simulation: {ok, gas_estimate, revert_reason|null, observed_at, block}}
```

### Executor interface (`docket/jobs/executors/base.py`; Lane B writes the Protocol, Lane D implements)

```python
@dataclass(frozen=True)
class Decision:
    kind: str                 # "noop" | "alert" | "action"
    summary: str
    prepared: tuple[PreparedCall, ...]
    evidence: dict
    observed_at: str
    block: int

class Executor(Protocol):
    category: str
    def evaluate(self, activation: Activation, *, reader=None) -> Decision: ...
    def within_policy(self, activation: Activation, decision: Decision) -> tuple[bool, str]: ...
```

Execution is done only by `docket/sessions/executor.py::execute(activation, prepared, *,
session, rpc)` (Lane B): simulate -> policy check -> sign -> `eth_sendRawTransaction` -> wait for
the receipt -> append a `Receipt`. Executors never hold keys and never send. Lane D registers
executors in `docket/jobs/executors/__init__.py::EXECUTORS: dict[str, Executor]` keyed by
category; Lane B's tick loop looks them up by `activation.category`.

### SessionPolicy (`docket/sessions/policy.py`, Lane B)

```
{contract_allowlist: [addr], function_allowlist: [4-byte selector hex], token_allowlist: [addr],
 per_action_limit_atomic: {token: amount}, total_cap_atomic: {token: amount},
 max_slippage_bps: int, max_gas_price_wei: int, expires_at: iso8601Z, emergency_pause: bool}
```
Session keys: `Account.create()` on the server, stored as an encrypted keystore JSON in the
`sessions` table; master password from the file named by `DOCKET_SESSION_KEY_FILE` (production
`/etc/docket/docket-sessions.key`, mode 0600, owned by `docket`; absent file = sessions refused,
never a default password). Revoke sweeps every allowlisted token and the remaining BNB minus gas to
`owner` and marks the session `revoked`. Funding: the owner sends the notional plus a small BNB gas
allowance to the session address from their own wallet (a browser step, `next_action.kind =
"fund_session"`); the server confirms funding by reading balances at a block.

### Verification levels (Lane E)

`registered` < `endpoint_detected` < `live` < `payment_tested` < `docket_tested` < `docket_verified`.
Each level names its evidence: probe record id, sample result hash, settlement tx, benchmark ref.
Listings expose `verification: {level, evidence: [...], verified_at}`.

### Marketplace summary (Lane A)

`GET /api/marketplace/summary` derives, never hard-codes: `services_total`,
`services_paid_stock`, `public_paid_hires` (settled `hire_payments` rows not produced by the
canary), `canary_settlements` (settled canary rows), `erc8004_identities`, `v3_families` (from
`report()`), `external_listings_by_level`, `activations_by_state`, `deployed_commit`
(`RELEASE-commit.txt` beside the package if present, else `git rev-parse HEAD`, else `"source"`),
`generated_at`. `index.html` counters are rendered from this object at startup (server-side, like
the existing shells) so the page stays complete without JavaScript.

## Lanes and ownership

| Lane | Owns | Must not touch |
|---|---|---|
| A product surface | `index.html`, `README.md`, `docs/submission/demo-script.md`, `docs/submission/README.md` lead, `docs/submission/bnb.md` lead, `docs/plans/2026-09-02-final-week.md` (mark stale items), `docket/api/summary.py` + its one `create_app` insert, `style.css`, `advantage.html` top one-page summary, the site nav on every existing page, `tests/test_marketplace_summary.py`, the copy-pinning tests | jobs/sessions/agents code, new pages |
| B activation backend | `docket/jobs/**`, `docket/sessions/**`, `docket/api/activations.py` + its one `create_app` insert, `store.py` (SCHEMA + migration only), `deploy/systemd/docket-jobs.{service,timer}`, `release.sh`/`preflight.sh` arrays, runbook count, `tests/test_release_scripts.py` count, `llms.txt`/`SKILL.md` activation sections, tests | HTML/JS, agents |
| C browser | `docket/api/web/js/**`, `activate.html`, `my-agents.html`, `search.html`, `providers.html`, `service.html` Activate button, page routes (one `@app.get` each, inserted directly above `app.mount("/static"`), `tests/e2e/**`, `.github/workflows/ci.yml` e2e job | backend logic |
| D1 range + health | `docket/agents/pancake/keeper.py`, `docket/agents/venus/shield.py`, `docket/jobs/executors/{range,health}.py`, `docket/hire/catalogue.py` entries for those two services, tests | grid/yield, sessions |
| D2 grid + yield | `docket/agents/grid/lifecycle.py`, `docket/agents/yield_router/migration.py`, `docket/jobs/executors/{grid,yield_router}.py`, `docket/hire/catalogue.py` entries for those two services, `docket/hire/admission.py` (dynamic limbs), tests | range/health, sessions |
| E marketplace supply | `docket/scan8004.py` (search), `docket/marketplace/{external,verification,providers}.py`, `docket/api/marketplace_api.py` + its one `create_app` insert, store tables, `docs/marketplace/` evidence, tests | catalogue internals |
| F agent advantage | `docket/advantage/v3/specs/v3-08-*.json`, `v3-09-*.json`, their calibration sets, runbooks, `report.py` summary block, `release.sh` family map, `docs/evidence-reproduction.md` count, judge-facing sentence regeneration, the spec_id registries in `spec.py`/`scoring.py`/`range_capture.py`/`rehearsal.py`, tests | v3-01..07 artifacts |
| G quality + ops | `ruff` config + fixes, `pip-audit` in CI, `/api/status`, `status.html`, `deploy/systemd/docket-probe.{service,timer}` + arrays, `.github/workflows/ci.yml` lint/audit jobs, `docs/deployment-runbook.md` status section | product code beyond lint |

Integration order (supervisor): B -> D1/D2 -> A -> C -> E -> F -> G, one PR per lane onto
`build/pivot-integration`, then one PR to `main`. Fable audits each lane before it merges.

## Integration and deploy checklist (supervisor; added 2026-09-03 14:00Z)

Merge order onto `build/pivot-integration`: A (done) -> B -> D1 -> D2 -> E -> C -> F -> G. Every
merge is followed by the full suite in the integration worktree; a lane merges only after its
Fable audit's blockers and majors are closed. Reconcile at integration:

1. Commit hygiene: no `Claude-Session:` or `Co-Authored-By` trailers survive (cherry-pick and
   reword where a lane's commit carries one).
2. `docket/jobs/executors/__init__.py` (Lane B's copy is the reference) must load the concrete
   executors — `range`, `health`, `grid`, `yield_router` — through Lane B's `load_executors()`
   without the import ring D1/D2 avoided.
3. Systemd unit count: B +2 (`docket-jobs`), F +2 (`docket-v3-yield-v8-capture`), G +2
   (`docket-probe`) => `deploy/systemd/` holds **21** files; `release.sh` and `preflight.sh`
   arrays, `tests/test_release_scripts.py` (`len(expected) == 21`), and
   `docs/deployment-runbook.md` ("all twenty-one tracked unit", exactly twice) all agree;
   `TIMER_NAMES` holds 10.
4. `docket/marketplace/registry.py`: `activation` for `range-doctor` and `health-guard` flips
   `one_shot` -> `policy_action` (and `tests/test_marketplace.py:501,569`) once Lane B's session
   executor is in the tree; grid-operator / yield-router likewise if D2's executors land.
5. `tests/test_web_w40.py`: Lane A's single nav for all pages, Lane C's `PIVOT_PAGES` split and
   Lane G's `status.html` exceptions collapse into ONE expectation (the plan's chrome contract,
   `?v=13`, on every page).
6. `index.html` experiment register: rows for `v3-08-yield-router` and `v3-09-health-guard`
   (or derive the rows from `report()` as the heading already is) so Lane A's register test
   passes with nine families; README/demo/submission custody sentences describe the integrated
   model (Lane A's follow-up text).
7. Judge-facing v3 sentence: Lane F's nine-family regeneration wins over Lane A's seven-family
   copy in the six docs; re-run `tests/test_judge_facing_state.py`.
8. Admission docs: with Lane D2's derived limbs, `fresh_paired_benchmark` reads true for
   range-doctor and solvent-signal until 2026-09-07 and for warden-scan until 2026-09-26. Every
   present-tense sentence that says the limb is false (`docs/api-and-payment-semantics.md:119-123`,
   `docs/submission/claims-checklist.md:78`, `docs/deployment-runbook.md:396-398,546-547`,
   `docs/submission/demo-script.md:21`) becomes a dated observation or is rewritten to the
   derived rule; `docs/operational-evidence.md` gets a new dated record after the deploy.
9. Lane E's `external_listings` table/level column names must match what
   `docket/api/summary.py::marketplace_summary` reads for `external_listings_by_level`.
10. Lane C's `api.js` must match Lane B's final auth message format and state names
    (`awaiting_session`, `revoking`) and Lane E's routes; re-run the Playwright suite against the
    integrated app (not mocks) before the PR.
11. `ruff check . --fix` after all lanes (Lane G linted the pre-pivot tree only); `pip-audit`
    on the final lock; `uv lock` if any dependency moved.
12. `llms.txt` / `SKILL.md`: every OpenAPI path documented (Lane A's summary route, Lane B's
    activations, Lane E's marketplace, Lane G's status); `test_llms_txt_documents_every_path_the_spec_declares`.
13. One PR from `build/pivot-integration` to `main`, merged with a merge commit (never squash:
    the v3-08/v3-09 registration witnesses are the lane commits). CI must be green on the head.

Deploy (Sep 4, outside every refusal window; Sep 5 11:49:54Z–12:03:06Z and Sep 6
11:49:54Z–12:03:06Z are refused):

- Host prerequisites BEFORE the release: `/etc/docket/docket-sessions.key` (48 random bytes,
  `0640 root:docket`) and `/etc/docket/docket-sessions.conf` (`DOCKET_SESSION_KEY_FILE=...`)
  for `docket-jobs.service` only — the web process never receives it; the existing
  `docket.service.d/archive.conf` already supplies `DOCKET_ARCHIVE_RPC` for pinned-block reads.
- `deploy/preflight.sh` (re-derive the nginx warn count), then `deploy/release.sh` with the CI-green
  commit; verify the smoke (`/services` still six ids, `/advantage/v3.json` nine families,
  `/api/status` `deployed_commit` == release), timers: `docket-jobs.timer` every minute,
  `docket-probe.timer` every 10 minutes, `docket-v3-yield-v8-capture.timer` armed for
  2026-09-06 11:50 UTC, `docket-v3-range-v7-capture.timer` still armed for 2026-09-05 11:50 UTC.
- Append dated records to `docs/operational-evidence.md` and `docs/source-deploy-manifest.md`.
- Tag `v1.0.0-hackathon` with `deploy/tag-release.sh` only after the deployed commit is verified.

Experiment schedule after the deploy: v3-07 stage 1 done (frame collected 2026-09-03); Sep 5
12:00Z pool-truth capture -> copy; Sep 7 (Codex back) v3-07 seats + lock + three owner manual
primaries + three settled agent primaries; v3-08 capture Sep 6 12:00Z -> copy; Sep 7 evening
v3-08 seats + lock (seats of a second family on the same day are permitted once the first
family's seats both passed); Sep 8 v3-08 primaries, v3-07 scoring seats, report; v3-09 frame
collection any day, its seats/lock/primaries after submission unless a day frees up.
