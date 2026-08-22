# Docket - security & correctness review

- **Repo**: `<repo>`
- **Branch/HEAD**: `docs/deliberation-round2` @ `fdf02cf`, 66 commits on `main..HEAD`
- **Date**: 2026-08-22. Read-only review; nothing in the repo was modified.
- **Test suite**: `./.venv/Scripts/python.exe -m pytest -q` -> **1 failed, 1209 passed, 2 warnings in 52.27s**

Every finding is tagged **[RAN]** (reproduced with a command whose output I read) or **[READ]**
(established by reading source only). No secret values are printed anywhere.

---

## HIGH

### H1. The only `async def` route performs blocking I/O - one hire freezes the whole site

- **Location**: `docket/api/routes.py:1046` (`async def hire`), calling `service.run()` ->
  `docket/hire/catalogue.py:149-174` (`httpx.request(..., timeout=30.0)` plus `time.sleep(1.0)`),
  and `docket/hire/x402.py:72-86` (sync `httpx.post` to the facilitator).
- **Category**: Denial of service / concurrency
- **Description**: `hire` is the *only* `async def` handler in the file (every other route is a
  plain `def`, which Starlette offloads to a threadpool). An `async def` handler runs directly on
  the event loop, so its blocking calls - outbound HTTP with 30s timeouts, `time.sleep` retry
  pauses, blocking BSC RPC round trips, and blocking sqlite writes - stall the single uvicorn
  worker for their entire duration. The runbook process definition
  (`docs/deployment-runbook.md:81-82`) starts one uvicorn worker with no `--workers`.
- **Proof [RAN]** - a real uvicorn server, a service whose `run` takes 6s:

```
BASELINE /health while idle: 0.328 s
slow POST /hire -> (200, 6.22)
/health issued 0.7s into that hire -> (200, 5.52)
```

  `/health` normally answers in 0.33s; issued 0.7s into a hire it took 5.52s, returning only when
  the hire finished. The loop was blocked for the whole request.
- **Impact**: one unauthenticated `POST /hire/warden-scan` against a hung upstream costs
  `UPSTREAM_TIMEOUT_S * UPSTREAM_ATTEMPTS + UPSTREAM_RETRY_PAUSE_S` = **61 seconds** of total site
  unavailability - `/`, `/agents`, `/hire`, `/canary`, the judge-facing HTML, everything. A handful
  of concurrent requests keeps the site down indefinitely. Compounded by H2 (no rate limit at all
  in the current configuration) and by the host running at load ~25 on 8 cores. This is the most
  likely way a judge meets a dead site during the 14-day window.
- **Fix**: make the handler synchronous and let Starlette's threadpool own it, or offload the
  blocking work:

```python
from starlette.concurrency import run_in_threadpool
result = await run_in_threadpool(service.run, payload)
# and likewise for facilitator.verify / facilitator.settle and the store writes
```

  Also add `--workers 2` (or `--limit-concurrency`) to the uvicorn unit.

### H2. The free-tier allowance is inert today, and trivially bypassable once enabled

- **Location**: `docket/api/routes.py:425-442` (`_spend_allowance`), `:1367-1371`, `:388`
- **Category**: Broken access control / rate limiting / DoS
- **Description**: three independent defects in one control.

**1. Inert.** `resets_in = _spend_allowance(client_ip) if payment_available else None` (`:1371`),
where `payment_available = paid_stock and pay_to is not None and facilitator is not None`.
`_spend_allowance` itself also returns `None` immediately when `pay_to is None` (`:432-433`).
**[RAN]** every service currently reports `paid_stock=False`:

```
range-doctor | grid-operator | health-guard | yield-router | solvent-signal | warden-scan
  -> paid_stock=False for all six
```

and the runbook (`docs/deployment-runbook.md:96-97`) confirms no settlement env is set.
**So there is presently no rate limit of any kind on `POST /hire/*`.** Each free call spends real
upstream budget: BSC RPC round trips, PancakeSwap explorer reads, and - for `warden-scan` - an
arbitrary caller-supplied blob relayed to `https://warden.gudman.xyz/api/demo/scan`
(`docket/hire/catalogue.py:183-185`), i.e. Docket is an open anonymous relay into your own Warden
deployment.

**2. Spoofable key.** The comment at `:429-431` states that the allowance is *"Keyed on the peer
address only"* because *"X-Forwarded-For is caller-controlled"*. That reasoning is correct but the
conclusion is false at runtime. **[RAN]** with the runbook's exact invocation:

```
effective proxy_headers = True | forwarded_allow_ips = 127.0.0.1
no header                    -> {'client_host': '127.0.0.1'}
XFF='203.0.113.9'            -> {'client_host': '203.0.113.9'}
XFF='attacker-rotates-this'  -> {'client_host': 'attacker-rotates-this'}
```

uvicorn 0.49.0 defaults to `proxy_headers=True, forwarded_allow_ips="127.0.0.1"`. Because nginx
proxies from loopback, `request.client.host` **is** the caller's `X-Forwarded-For`. Rotating that
header gives unlimited free-tier hires.

**3. Unbounded memory.** `hires: dict[str, tuple[float, int]]` (`:388`) is only ever written per
key; there is no eviction sweep. With (2), an attacker mints one dict entry per distinct XFF
string. Over a 14-day unattended window that is an OOM path on a box already at load ~25. **[READ]**

- **Impact**: unmetered abuse of paid stock once settlement is enabled for judging; unmetered
  amplification into your upstreams today; memory exhaustion of the judged process.
- **Fix**: start uvicorn with `--no-proxy-headers` **and** key the allowance on a value you trust;
  or keep proxy headers and have nginx overwrite (not append) `X-Forwarded-For` with `$remote_addr`.
  Apply the allowance to *every* hire, not only `payment_available` ones. Evict expired windows on
  each call and hard-cap the dict size. Add an nginx `limit_req` zone as the outer defence.

### H3. Netguard's SSRF check is defeated by DNS rebinding, and the result is published

- **Location**: `docket/netguard.py:62-89` (`check_url`), `docket/liveness.py:72-89`
- **Category**: SSRF
- **Description**: `check_url` resolves the hostname and classifies every returned address, then
  returns. `client.get(url, ...)` then performs an **independent second resolution**. Nothing pins
  the vetted address. Endpoint URLs come from an on-chain registry anyone can write to
  (`docket/netguard.py:3-4` says so), so the attacker owns the DNS zone and can serve a TTL-0
  record: public IP to the guard, `127.0.0.1` or `169.254.169.254` to the connect.
- **Proof [RAN]** - the two lookups are structurally independent, so a rebinding record needs no
  timing luck:

```
netguard verdict on the attacker-controlled host: True | ok
probe outcome recorded and published: responded status_code: 418
```

  The guard passed the host believing it was `93.184.216.34`; the probe connected to a
  loopback-only service and recorded HTTP 418.
- **Impact**: semi-blind SSRF from the VPS. `status_code` and `elapsed_ms` are persisted
  (`docket/liveness.py:63-90`) and served publicly on `/agents/{agent_id}`, so an attacker gets a
  status-code and timing oracle for loopback and RFC1918 services on a box that hosts many other
  vhosts. `follow_redirects=False` and GET-only limit it to reads, and it fires only when an
  operator runs an ingest sweep - but a fresh sweep before judging is exactly what
  `docs/deliberation/CODEX-ASSESSMENT-2026-08-14.md:46` says is planned.
- **Fix**: resolve once and connect to that address. Either pass the vetted IP into httpx and set
  the `Host` header, or install a custom `httpx.HTTPTransport` whose socket connect is restricted
  to the address `check_url` approved. Re-validate the peer address after connect
  (`socket.getpeername()`) as a belt-and-braces check.

### H4. CI is permanently red from 2026-08-21 onward, and the repo goes public with it

- **Location**: `tests/test_advantage_v3_capture.py:279-284`;
  `docket/advantage/v3/capture.py:186-198`, `:46` (`ATTEMPT_OFFSETS_S = (0, 60, 120)`);
  `.github/workflows/ci.yml:16-22`
- **Category**: Release / evidence integrity
- **Description [RAN]**: the one failing test is date-dependent, exactly as briefed, but the framing
  matters. `capture.main()` is called against the **real system clock**. The registered window
  opened `2026-08-21T12:00:00Z` and closed at `12:02:00Z`. Before it, `main` prints "Capturing
  early..."; after it, it prints "the registered capture opened at 2026-08-21T12:00:00Z and it is
  now ...". Both exit `2`, so `assert code == 2` still passes; the message assertion can **never**
  pass again.

```
E  AssertionError: assert 'Capturing early' in 'capture refused: the registered capture
   opened at 2026-08-21T12:00:00Z and it is now 2026-08-22T13:01:02...'
tests/test_advantage_v3_capture.py:284
```

  `ci.yml` runs `python -m pytest -q` and its branch filter is `[main, "docs/**"]`, which **does**
  cover `docs/deliberation-round2` - so every push from here on shows a red run.
  `docs/operational-evidence.md` already notes the last green run covered `aaba01a`, twelve commits
  behind HEAD.
- **Impact**: a judge who opens a public repo sees a failing CI badge and a red Actions tab on a
  project whose entire pitch is verifiable evidence. This is a submission-blocking presentation
  risk.
- **Fix**: inject the clock the test asserts on rather than reading `datetime.now`, and add a
  sibling test pinned *after* the window that asserts the late-refusal wording. Do not simply
  delete the assertion - it is the one that distinguishes the two refusal reasons.

---

## MEDIUM

### M1. Public flip exposes the VPS IP with a root SSH recipe, and the operator's Windows paths

- **Location**: `docs/plans/2026-08-06-phase0-foundations.md:470-473`; plus 14 tracked files
  carrying the operator's Windows home path (`docs/deliberation/CODEX-ASSESSMENT-2026-08-14.md`
  x36, `CODEX-EXEC-AUDIT-2026-08-14.md` x29, `CODEX-WIN-SPEC-2026-08-14.md` x15,
  `BUILD-BRIEF-RUNNER-ORCHESTRATOR.md` x1, and 10 files under `docs/plans/`)
- **Category**: Information disclosure
- **Description [RAN]** (git grep over HEAD, and git log -p over all 1,981 objects): four lines
  publish the shared VPS address together with a root SSH login and scp targets for a *different*
  project's vhost and webroot. Separately, about 102 occurrences across 14 files leak the
  operator's Windows username and full directory layout. There is **no credential** in any of
  them. Kind: infrastructure address, account name, filesystem layout.
- **Impact**: hands a hostile reader the exact host to point a scanner at, tells them root SSH is
  the operating model, and names a co-located project's config path. It also fingerprints the
  author's machine. None of it is exploitable alone; all of it lowers the cost of an attempt
  against a box carrying many other vhosts.
- **Fix** - two honest options, neither free:
  - **Redact and accept history.** Replace the four lines with a placeholder host and rewrite the
    Windows paths to repo-relative ones in a new commit. Faster, but git history still carries the
    originals.
  - **Rewrite history** (git filter-repo). Actually removes them, but every commit SHA changes -
    which breaks the backlog entries pinned to commits, the operational-evidence claim that
    `git cat-file -t aaba01ae...` resolves, the recorded CI head SHA, and the commit-named deploy
    identity. For a project whose value is a commit-pinned evidence chain, this is expensive.

  Recommendation: redact in a new commit and price the residual disclosure down by hardening the
  host (key-only SSH, no root login, fail2ban). A history rewrite costs more evidence than it buys
  secrecy, because the IP is already resolvable from the public hostnames the repo ships.

### M2. A settled payment can leave the buyer with no result and no self-service recovery

- **Location**: `docket/api/routes.py:1296-1344`; `docket/store.py:237-303`
- **Category**: Payment correctness / funds at risk
- **Description [READ]**: the ordering is right in the common case - work runs, output is bound,
  *then* settlement is attempted, and the result is returned only after `finish_payment`. But if
  `facilitator.settle()` succeeds on chain and the HTTP response is lost, the handler records
  `settlement_unknown` and returns 502 without the result. The result **is** persisted
  (`record_payment_output` writes `result_json`), yet **no route reads it back**: re-presenting the
  nonce returns 409 `settlement_pending_reconciliation` forever (`:1167-1173`), and there is no
  receipt-retrieval route anywhere in `routes.py`.
- **Impact**: a judge whose hire hits a facilitator timeout is charged 0.50 $U, gets a 502, and has
  no way to obtain what they paid for. `docs/deployment-runbook.md` contains no reconciliation
  procedure, so recovery depends on the owner being awake - during a 14-day unattended window.
- **Fix**: add a recovery route authenticated by re-signing the same nonce, returning the stored
  `result_json` and receipt for a `settled` or `settlement_unknown` row without re-running work or
  re-settling. Document the reconciliation step in the runbook.

### M3. No security response headers and no CSP anywhere

- **Location**: `docket/api/routes.py` (no header middleware); `docket/api/web/*.html` (no CSP meta)
- **Category**: Security misconfiguration
- **Description [RAN]**: a case-insensitive grep for content-security-policy, x-frame-options,
  referrer and strict-transport over `docket/`, `deploy/` and the runbook returns **nothing**. The
  nginx site is host-managed and not in the repo, so there is no evidence any header is set. This
  matters more than usual because the UI builds essentially every view with `innerHTML` and
  template literals.
- **Impact**: no defence-in-depth if a single escaping site is ever missed; the site can be framed;
  full referrers leak to any outbound link.
- **Fix**: add a small middleware (or nginx add_header) for a strict Content-Security-Policy
  limited to self, with `frame-ancestors 'none'` and `base-uri 'none'`, plus
  `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. The UI ships no inline
  scripts and makes zero external requests (verified below), so a strict policy will not break it.

### M4. Four package-data globs match nothing, beside a comment claiming they carry the evidence

- **Location**: `pyproject.toml:52-62` (`v3/inputs/*.json`, `v3/runs/*.jsonl`,
  `v3/sheets/*/*.json`, `v3/mappings/*.json`)
- **Category**: Evidence integrity / packaging
- **Description [RAN]**: none of those four directories exists on disk or in git. The comment above
  them says an install must carry them so it can "reconstruct the same state as the checkout
  instead of silently dropping a ledger or a prompt-blinded score sheet". Today the checkout has no
  ledger and no score sheet to drop. `setuptools` tolerates non-matching globs, so nothing errors -
  the claim just is not true yet.
- **Impact**: a judge who reads `pyproject.toml` before running anything is told artifacts exist
  that do not.
- **Fix**: either land the artifacts or move the comment into the future tense. On the `packages`
  list itself: **[RAN]** `find docket experiments -name __init__.py` yields exactly the 15 entries
  `[tool.setuptools] packages` declares - no subpackage is missing from the wheel.

---

## LOW / INFO

### L1. The v3 advantage machinery has zero runs, and its one registered capture moment has elapsed

- **Location**: `docket/advantage/v3/specs/*.json` (`inputs_sha256` is empty in all three);
  `deploy/systemd/docket-v3-capture.timer` (`OnCalendar=2026-08-21 12:00:00 UTC`,
  `Persistent=false`); `docs/deliberation/AUDIT-BACKLOG.md:377-390`
- **Category**: Evidence claim, not a vulnerability
- **[RAN]** `docket.advantage.v3.report.report()` returns
  `{"states": {"registered_waiting_for_inputs": 3}, "refuted": [], "not_refuted": []}` - which is
  *honest*, and the page says it is waiting rather than implying a result. That is to the code's
  credit. But all three `inputs_sha256` are empty, `docket/advantage/v3/inputs/` does not exist, and
  the Yield capture's single registered moment passed yesterday with nothing recorded in the repo.
  The backlog's own words: "Zero real seat runs exist. This is machinery with no evidence through it
  yet."
- **What a judge sees**: 110KB of `spec.py`, 64KB of `scoring.py`, a red CI run (H4), and an
  advantage report with three empty families. Decide before the flip whether to run the machinery or
  to lead with what *is* evidenced (the v2 corpus, the LP journal, the canary).

### L2. Operator forgeability of v3 results is real and self-documented

- **Location**: `docs/deliberation/AUDIT-BACKLOG.md:377-390`;
  `docket/advantage/v3/calibration_driver.py:95-126`
- **[READ]**: the ledger lives on the operator's filesystem. The module refuses a second capture and
  chains each attempt to the previous response digest, so a *deleted* attempt leaves a dangling link
  - but an operator who owns the disk can delete a seat directory and start over, or run a model out
  of band and record `no_response`. The stated mitigation (commit artifacts as written, so the
  remote history anchors them) is **not implemented**. `verify_calibration_capture` exists, is
  tested, and **nothing calls it** - an envelope assembled by hand still locks.
- **Also [READ]**: `_refuse_shared_session` (`:95-126`) scans the seat directory and then
  `open_attempt` writes - two concurrent invocations both pass the scan. TOCTOU; single-operator
  local tool, low impact, and the backlog already names it at line 630.
- **Fix worth doing before judging**: have the assembly path call `verify_calibration_capture`, and
  commit and push each artifact as it is written so the remote history is the anchor. Do not claim
  deletion-proofness; the module's honesty here is a strength - keep it.

### L3. `_warden_vocabulary` falls back to the answer key when the vendor snapshot ref is absent

- **Location**: `docket/advantage/v3/scoring.py:1366-1379`
- **[READ]**: if `inputs["vendor_snapshot"]["ref"]` is missing or empty, or `repo_root is None`, the
  vocabulary is derived from `case["labels"]` - the key itself. The check "is this class one the
  vendor actually publishes" silently becomes "is this class one we expected". It is not currently
  reachable in production: `assert_runnable` (`spec.py:2474-2489`) rehashes the locked inputs and
  `_validate_inputs` runs, so a lock without a vendor ref would have to be registered that way
  deliberately. **[RAN]** the only tests touching this path set `vendor_snapshot` explicitly
  (`tests/test_advantage_v3_scoring.py:36`); the fallback branch is untested.
- **Fix**: make the fallback a refusal for `v3-03-warden-security`. A self-certifying vocabulary is
  precisely the thing an auditor will pick on.

### L4. The calibration driver imports and executes an arbitrary module:callable

- **Location**: `docket/advantage/v3/calibration_driver.py:69-92`, `:235`
- **[READ]**: `import_module(module_name)` on a CLI argument. By design and operator-only. It becomes
  a privilege-escalation path only if the CLI is ever driven from a unit whose `EnvironmentFile` or
  arguments are writable by a less-privileged account. It is not today. Noted so it does not get
  wired into a timer later without thought.

### L5. Systemd units and the runbook disagree about where the deployed venv lives

- **Location**: `deploy/systemd/docket-v3-capture.service` and `docket-lp-record.service` (comments
  say the deployed venv lives at `/opt/docket-venvs/<commit>` while `/opt/docket/docket` is the
  PREVIOUS release's source tree) versus `docs/deployment-runbook.md:58-88` (a copied release at
  `/opt/docket` with its own `.venv`, back-up-then-replace)
- **[READ]**: all three units nonetheless run `ExecStart=/opt/docket/.venv/bin/python`. The units
  correctly avoid *path* arguments into `/opt/docket/docket`, but the **interpreter** is not
  commit-pinned. If `/opt/docket/.venv` is ever the previous release's environment, every timer
  silently records against the wrong revision - the exact failure the comments were written to
  prevent. Reconcile the two documents and, if the commit-named venv model is real, point
  `ExecStart` at it (or make `/opt/docket/.venv` a symlink flipped atomically at release).
- **Related 14-day fragility [READ]**: the application unit is host-managed and *not in the repo*,
  so there is no visible `Restart=always`. If uvicorn dies (plausible under H1 plus H2 on a box at
  load ~25), nothing restarts it; the canary runs once daily at 04:17 UTC and only *records* a
  failure - it does not recover the service. Worst case a judge meets a dead site for ~24h. Add
  `Restart=always` and `RestartSec=5` and a watchdog, and track the unit in the repo.
  `DOCKET_CANARY_END_AT=2026-09-24T00:00:00Z` correctly covers the judging window - that part is
  right.

### L6. Personal email in 5 commit-author records

- **[RAN]**: 5 `Author:` lines use the personal address; all other commits use the GitHub noreply
  address. No email appears in any blob - metadata only. Removing it means rewriting history, with
  the same SHA-breakage cost as M1. Probably accept it.

### L7. `/agents` full scan - measured, and currently harmless

- **Location**: `docket/api/routes.py:669-736`, `:738-745` (`store.iter_agents(sid)` drained per
  request)
- **[RAN]**: I expected an amplification vector and measured instead:

```
snapshot 3  agents 506
iter_agents full scan: 0.02 s for 506 rows
```

  The served snapshot holds 506 agents; a full scan costs 20ms. Recording it as **not** a finding at
  current data size. It becomes one if a pre-judging sweep widens the population (the docs discuss
  247,065 registry entries) - at that scale `GET /agents?limit=1` would cost a full table scan and
  `/agents/{id}` would materialise every row into a dict.

---

## Areas checked and found sound

- **EIP-712 / EIP-3009 verification** (`docket/hire/x402.py:138-240`) **[READ]** - binds
  `chainId=56`, `verifyingContract=asset`, the exact advertised domain, the canonical field set
  (rejects extra or missing keys), exact `value == amount`, `recipient == payTo` case-insensitively,
  `network == eip155:56`, **both** `validAfter` and `validBefore`, a 32-byte hex nonce, and recovers
  the signer against the declared payer. `accepted != expected_requirements` is a whole-object
  equality check, so offer, asset, amount and recipient cannot be substituted. The
  `docs/deliberation/CODEX-ASSESSMENT-2026-08-14.md:78` finding ("omits settlement, asset-domain
  binding, replay protection, and validAfter") is **fixed at HEAD** by `f94a8e0`.
  Residual, protocol-level, worth one line in the docs: the EIP-3009 signature covers only
  `(from, to, value, validAfter, validBefore, nonce)`, so a captured `X-PAYMENT` header is a bearer
  credential over TLS - the nonce binding in the store is what prevents its reuse, not the
  signature.
- **Replay protection** (`docket/api/routes.py:1144-1236`, `docket/store.py:183-303`) **[READ]** -
  durable nonce state in sqlite, not memory. Every terminal status has its own 409, a mismatched
  binding is refused before any facilitator call, and `reserve_payment` closes the concurrent-claim
  race with a conditional INSERT. The state machine is genuinely one-way: each transition is a
  `WHERE status = <expected>` UPDATE that raises on `rowcount != 1`. Work is never delivered without
  settlement, and an unadmitted service never charges (`:1416-1424` records `not_for_sale` with
  `authorization_used: False`).
- **The v3 input lock** (`docket/advantage/v3/spec.py:2474-2489`) **[READ]** - `assert_runnable`
  re-reads the referenced file, recomputes SHA-256, and compares with `hmac.compare_digest`. The
  earlier "never opens inputs_ref or recomputes its digest" finding is **fixed at HEAD** by
  `8125fc0`. `save()` additionally enforces that stage two may change only `inputs_sha256`.
- **XSS** (`docket/api/web/app.js`) **[RAN and READ]** - every template interpolation of a registry-
  or upstream-supplied string passes through `escapeHTML`. Chain-supplied names, descriptions,
  `name_family`, owner addresses and endpoint URLs are all escaped; endpoint URLs are rendered as
  monospace list-item text, never as an href. Warden's `sanitized_payload` - the most dangerous
  string on the site - is escaped and placed in a `pre` block (`app.js:696-703`). The `escapeHTML`
  table covers the five HTML metacharacters, correct for both text and quoted-attribute contexts.
- **Zero external requests [RAN]** - a grep for absolute http(s) src/href, `@import` and CSS `url()`
  over `docket/api/web/*.html` and `*.css` returns nothing. `app.js` makes exactly two fetch calls,
  both to relative same-origin paths. The house rule holds.
- **CORS** (`docket/api/routes.py:401-406`) **[READ]** - wildcard origins with `allow_methods=["GET"]`
  and `allow_credentials=False`. No wildcard-with-credentials. `POST /hire` is therefore not
  cross-origin reachable.
- **SQL injection** (`docket/store.py`) **[READ]** - every statement is parameterised. The two
  dynamically built strings (`iter_agents:602-608`, `iter_endpoints:628-635`) append only fixed
  literal fragments; f-strings appear solely in exception messages.
- **Input validation** (`docket/hire/catalogue.py:188-339`) **[READ]** - `_declared_integer` rejects
  bools and non-ints; `_declared_number` rejects NaN, Inf and negatives; `token_id` and
  `observation_block` reject floats-with-fraction and non-positive values; `limit` is hard-capped by
  `MAX_EXAMINED`; `/agents` clamps `limit` to 1..100 and `offset` to >= 0. Caller-supplied frozen
  snapshots are SHA-256-checked against their own declared digest before use.
- **Canary token** (`docket/api/routes.py:464-472`) **[READ]** - `hmac.compare_digest`, fail-closed
  when the token is unconfigured or the service id does not match, and a present-but-wrong header is
  a 403 before any work runs.
- **Secret material [RAN]** - full-history scan (`git log -p --all`, 5.3MB, all 1,981 objects):
  **no** private keys, mnemonics, .env contents, PEM blocks, or API tokens. A prefix sweep for the
  common AWS, GitHub, Anthropic, OpenAI, Slack, JWT and PEM markers returns zero hits. All 197
  distinct 64-hex values are SHA-256 digests, transaction hashes, or the ERC-20 Transfer topic. No
  .db, .sqlite, .env, .key or .pem file was ever added in any commit
  (`git log --all --diff-filter=A`). `data/agents.sqlite3` is 44MB on disk, `data/` is in
  `.gitignore`, and it has **never been committed**. `build/`, `dist/`, `*.whl` and `*.egg-info/`
  are all ignored. The working tree is clean - no untracked file would be swept in by the flip. Keys
  are env-gated only (`DOCKET_SETTLE_KEY`, `DOCKET_CANARY_PRIVATE_KEY_FILE`) and the installer
  generates its token with `secrets.token_hex(32)` without printing it
  (`deploy/install-canary.sh:82-93`). `docket/store.py:139-157` additionally refuses to persist
  canary fields named like payment material. The one on-chain identifier the repo publishes on
  purpose is the controlled-LP wallet and token id in `deploy/systemd/docket-lp-record.service` -
  that is evidence, not a leak, but note it permanently links that wallet to the operator.
- **install-canary.sh [READ]** - `set -euo pipefail`, `umask 077`, root check, source-existence
  checks, backup-before-replace under a UTC-named directory, correct root:docket 0640 ownership on
  config and token, `trap cleanup EXIT` on both temp files, and it deliberately starts nothing. This
  is the strongest file in the deployment set.
- **Hardcoded upstreams** (`docket/agents/pancake/pools.py:29-32`, `docket/scan8004.py:16`,
  `docket/hire/catalogue.py:86-87`) **[READ]** - the pools URL, token list, 8004scan base and both
  relayed services are compile-time HTTPS constants with no user-controlled component, and httpx's
  default `follow_redirects=False` applies to all of them. The only attacker-controlled outbound URL
  in the system is the liveness probe, which is H3.
- **Unit hardening** (`deploy/systemd/*.service`) **[READ]** - `NoNewPrivileges`, `PrivateTmp`,
  `ProtectHome`, `ProtectSystem=strict`, `ReadWritePaths` scoped to `/var/lib/docket`, `UMask=0027`,
  non-root `User=docket`, `TimeoutStartSec` on all three, `Restart=no` (correct for oneshots).
- **CI branch coverage [RAN]** - `.github/workflows/ci.yml` triggers on `[main, "docs/**"]` plus all
  pull requests, so the working branch `docs/deliberation-round2` **is** covered. The `package` job
  builds the wheel, installs it into a venv outside the checkout, and smoke-tests with `-I` so the
  source tree cannot shadow the install. This is correct and was worth the fix in `aaba01a`.

---

## Summary

| # | Severity | Title | File |
|---|----------|-------|------|
| H1 | HIGH | Blocking I/O in the only `async def` route freezes the whole site | `docket/api/routes.py:1046` |
| H2 | HIGH | Free-tier allowance inert today, XFF-spoofable and unbounded once enabled | `docket/api/routes.py:425`, `:1371`, `:388` |
| H3 | HIGH | Netguard SSRF check defeated by DNS rebinding; status codes published | `docket/netguard.py:62`, `docket/liveness.py:81` |
| H4 | HIGH | CI permanently red after 2026-08-21 on a repo about to go public | `tests/test_advantage_v3_capture.py:284` |
| M1 | MEDIUM | VPS IP plus root SSH recipe and operator Windows paths in tracked docs and history | `docs/plans/2026-08-06-phase0-foundations.md:470` |
| M2 | MEDIUM | `settlement_unknown` can charge a buyer with no path to the stored result | `docket/api/routes.py:1296` |
| M3 | MEDIUM | No CSP or security response headers anywhere | `docket/api/routes.py` (absent) |
| M4 | MEDIUM | Four package-data globs match nothing while claiming to carry the evidence | `pyproject.toml:52` |
| L1 | LOW | v3 machinery has zero runs; registered capture moment has elapsed | `docket/advantage/v3/specs/*.json` |
| L2 | LOW | v3 results operator-forgeable; `verify_calibration_capture` never called; session TOCTOU | `docket/advantage/v3/calibration_driver.py:95` |
| L3 | LOW | `_warden_vocabulary` self-certifying fallback, untested | `docket/advantage/v3/scoring.py:1366` |
| L4 | INFO | Calibration driver imports arbitrary code (operator-only, by design) | `docket/advantage/v3/calibration_driver.py:69` |
| L5 | LOW | Units vs runbook disagree on the deployed venv; no `Restart=` on the app unit | `deploy/systemd/*.service`, `docs/deployment-runbook.md:58` |
| L6 | LOW | Personal email in 5 commit-author records (metadata only) | git metadata |
| L7 | INFO | `/agents` full scan - measured at 20ms / 506 rows, not a finding today | `docket/api/routes.py:669` |

**Verified by running**: pytest (1 failed / 1209 passed / 52.27s); event-loop blocking under a real
uvicorn server; uvicorn X-Forwarded-For client-host rewriting; netguard rebinding TOCTOU; live
service admission states; `iter_agents` scan timing against the real 44MB database;
`advantage.v3.report()`; full git-history secret sweep; package list versus on-disk `__init__.py`;
app.js escaping and external-request greps; CI branch-filter match; v3 spec `inputs_sha256` state
and missing artifact directories.

**By reading only**: EIP-712/3009 field binding; payment state machine and replay semantics;
`settlement_unknown` recovery gap; SQL parameterisation; input validators; `hires` dict growth;
calibration-driver TOCTOU and seat resolution; systemd/runbook divergence; installer review.

**Not assessed**: the live host itself (nginx config, TLS, firewall, the actual `docket.service`
unit, whether the Aug 21 capture ran on the VPS) - none of it is in the repo, and this review was
read-only against the checkout.
