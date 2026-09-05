# Operational evidence — what is running, as opposed to what is written

The auditor of record runs under a read-only sandbox with no network. That is deliberate: an
auditor that could reach production could also change it, and its clearance would then be partly
a statement about its own edits. The cost is that it cannot check anything operational, so
several backlog entries were cleared "in code" and left open on deployment.

This file moves the legwork instead of loosening the sandbox. The evidence below was collected
by the builder from the two places the auditor cannot reach — the host and GitHub — and committed
so it can be audited under read-only like anything else.

Competition context: the BNB Chain main track has one $30,000 winner plus official
adoption; it is not a shared prize pool.

**What this file is worth, stated precisely.** It does not let a reader verify the host. It lets
a reader check the collection for *internal consistency*: whether the deployed revision resolves
to a real commit in this repository, whether the code that commit contains matches what the live
endpoint served, and whether the recorded digests agree. A collector who wanted to lie could lie
here. What they could not easily do is stay consistent with the tree while doing it.

---

## Collected 2026-08-16 (refreshed after the 12:20Z deploy)

### Deployed identity

| Field | Value |
|---|---|
| Host | `docket.gudman.xyz` |
| `/opt/docket/.venv` resolves to | `/opt/docket-venvs/534af826575a` |
| `RELEASE-commit.txt` | `534af826575a3c316eaace03b5e41ab077d4c253` |
| Wheel sha256 | `b8c9a257c9ab3acab111b87d2507153b7d0a7bd54a41ef9110a2a57c88758beb` |
| Services active | `docket.service`, `docket-lp-record.timer`, `docket-v3-capture.timer` |

**Checkable without leaving the repository:** `git cat-file -t 534af826575a3c31…` resolves to a
commit, and `git rev-parse 534af826575a` returns exactly that hash. This record was written by
`printf` from the client's `git rev-parse` and echoed back for comparison, not typed.

⚠️ **The record this one replaced was wrong, and the error was mine.** The previous deploy's file
read `81addbb7796d3e0b` — the correct twelve-character release id followed by four characters I
invented while padding it out by hand. The first twelve matched a real commit, which is what made
it look precise. A provenance file exists so running code can be tied to a commit; a hash that
resolves to nothing makes it un-tieable while appearing exact. It was corrected in place before
this deploy, and the rule the mistake earned is that a release records nothing it did not compute.
The first deploy's record (`3873e2c460da…`) was always correct and was left alone.

### Entry 2 — BSC proof-of-authority middleware, in the deployed package

Read from the installed package inside the running venv, not from the checkout:

```
docket.agents.pancake.positions  contains ExtraDataToPOAMiddleware : True
```

### Entry 7 — the renamed rate fields, as actually served

`POST https://docket.gudman.xyz/hire/range-doctor` → 200, body sha256
`dab25305b5b66fb388e3f7ef7528b502839c719df8873e484cd677168fff95ed`, observation block
`116268853`.

```
economic_consequence.pool_net_apr_if_in_range present : True
economic_consequence.position_fee_apr           absent : True
```

The deployed package agrees: `doctor` contains `pool_net_apr_if_in_range` and does not contain
`position_fee_apr`. So the rename is live, not merely committed.

### Entry 12 — the CI run

| Field | Value |
|---|---|
| Run | `31943515697` |
| Head SHA | `aaba01ae70b0c89e0417e8ef4949c82757fde78f` |
| Created | 2026-08-16T11:08:21Z |
| Conclusion | **success** |
| Jobs | `test` success, `package` success |

`git cat-file -t aaba01ae70b0…` resolves in this repository, so the run's head is a commit here
rather than an unrelated reference.

### The daily LP record is running unattended

`/var/lib/docket/lp-record/controlled.jsonl` holds **2 lines**. The second was written by the
timer at 06:00Z without anyone starting it, which is the claim the first line alone could not make.

---

### The audit remediation is deployed (2026-08-16T12:20Z)

`534af826575a` is live and the four fixes were read back out of the venv the service imports
from — exclusive capture writes, per-attempt journalling, the calibration digest check, and
`still_held`. The registered Yield capture at 2026-08-21T12:00:00Z failed: the service exited
2, wrote nothing to `/var/lib/docket/v3-capture/`, and the volatile journal rotated before its
refusal text could be recovered. Before any input lock, Yield was recommitted once to
2026-08-26T12:00:00Z; `inputs_sha256` remains empty. The LP journal came through the swap at
2 lines.

---

## What this evidence does not establish

- ⚠️ **The service takes about eight seconds to accept connections after start.** A post-deploy
  check at six seconds returns `000` on every endpoint and reads exactly like an outage. Both
  deploys hit this. Wait, then re-check, before concluding anything.
- The CI run covers `aaba01a`, not `HEAD`. Commits after it have not been checked by any runner.
- Every figure here was gathered by the builder. It is consistent with the tree, which is the
  property a reader can actually test; it is not independent.

---

## Collected 2026-08-22 (after the `d9f1351` release)

This release shipped the nine reviewed workstreams behind `JOINT-AUDIT-2026-08-22.md`. It was the
first release performed by `deploy/release.sh` rather than by hand, and the first time any of this
code had run on Linux — CI run `32587545388` on `d9f1351` is the other half of that statement.

### Deployed identity

| Field | Value |
|---|---|
| Host | `docket.gudman.xyz` |
| Release commit | `d9f1351705acdce480a15806f0d5d0f92f60cb73` |
| `/opt/docket/.venv` resolves to | `/opt/docket-venvs/d9f1351705ac` |
| Runtime `docket.__file__` | `/opt/docket/.venv/lib/python3.12/site-packages/docket/__init__.py` |
| Wheel sha256 | `819c468cde7517eddd28fd9a6e1fe05c5c4573fd4f02c80fb2c80a9aae58dacf` |
| Previous release retained at | `/opt/docket.bak-20260822T172841Z` |
| Database backup | `/var/backups/docket/agents-20260822T172707Z.sqlite3`, `PRAGMA integrity_check` = ok, taken with the app running via the SQLite backup API |
| Health | accepted on poll attempt 1 of 30 |

Read from the installed package inside the running venv, not from a checkout:
`docket.agents.pancake.positions` contains `ExtraDataToPOAMiddleware`: `True`;
`docket.advantage.v3.seats.codex_cli` imports; `docket.identity.register.REGISTRATION_BASE_URL`
is `https://docket.gudman.xyz/registrations`.

### The registry snapshot is no longer stale, and it moved without a restart

The first `docket-refresh.service` run promoted **snapshot 5** at `2026-08-22T17:41:38Z`
(`Docket refresh: promoted snapshot 5`, exit 0, 85 s wall, 5.9 s CPU). The serving process was
**not restarted** — `systemctl show docket.service` reported `NRestarts=0` and an
`ActiveEnterTimestamp` from the release itself — and `GET /stats` immediately answered:

```
snapshot_id 5 · captured_at 2026-08-22T17:40:29Z · snapshot_age_seconds 99
sampled 510 / expected 510 · complete true · population "min_feedbacks>=1"
endpoints_responded 20 / endpoints_attempted 23 · registry_total 247146
refresh_status {"status": "ok", "timestamp": "2026-08-22T17:41:38.713181+00:00"}
```

The snapshot it replaced was captured `2026-08-07T17:51:02Z` and was 15 days old. `population`
now states the filter instead of reading `unspecified`.

### The capture rehearsal, on this host, with the installed code

The 2026-08-21 capture failed because the process was started *at* its registered moment and spent
its five-second tolerance importing on a loaded host. The redesigned unit pre-arms. Rehearsed here
against a scratch specification whose `spec_id` is `v3-02-yield-router-REHEARSAL-NOT-REGISTERED`,
written to `/var/tmp/docket-rehearsal/` — not to `/var/lib/docket/v3-capture/` and never against
the registered protocol hash:

- `armed.json` was written at `17:33:24.915366Z` for a registered moment of `17:39:00Z` — five and
  a half minutes early — carrying the three-attempt schedule, the host identity, the spec hash, and
  a preflight recording a timezone-aware clock, a writable directory and 933 GB free.
- The process then waited, and captured on attempt 1: both URLs returned 200, observed at
  `17:39:02.458871Z` and `17:39:02.879275Z`, inside the attempt's own minute.
- Bodies were persisted with their digests (`pools` 38,926 bytes `5797b062…`, `token-list`
  216,263 bytes `703da7f5…`), per-attempt files were written as the attempt finished, and
  `capture-complete.json` was written last.

The registered timer was armed for `Wed 2026-08-26 11:50:00 UTC`, ten minutes ahead of the
recommitted moment. Yield then captured its registered source bytes on the first scheduled attempt
at `2026-08-26T12:00:00Z`; Range did the same at `2026-08-26T12:10:00Z`. These captures are input
evidence only. At this collection point neither input had yet been locked; the later
2026-08-28 committed-artifact observation below supersedes that historical state. The retired
2026-08-21 timer was removed by the release.

### Persistent journal — configured, then found not to have taken effect

The release installed `/etc/systemd/journald.conf.d/docket.conf` (`Storage=persistent`,
`SystemMaxUse=512M`) and restarted `systemd-journald`, and `systemd-analyze cat-config` confirmed
the drop-in was read. **It was still writing only to `/run/log/journal`, and `/var/log/journal` did
not exist** — the volatile condition that destroyed the Aug-21 refusal text. On this systemd the
drop-in alone does not create the directory. Repaired by hand at `17:30Z`:
`install -d -m 2755 -o root -g systemd-journal /var/log/journal`, `systemd-tmpfiles --create
--prefix /var/log/journal`, `journalctl --flush`. `journalctl --header` then listed five
`/var/log/journal` paths and `journalctl --disk-usage` reported 256.3M. The release script's own
failure to verify this is recorded as a defect and fixed separately; a release that reports success
while leaving logging volatile is the exact class of silence this project exists to remove.

### The canary now exercises the controlled position, and fails honestly

`/etc/docket/docket-canary.conf` previously carried only a base URL, service id and token path, so
the LP and settlement legs recorded `controlled_live_lp_absent, configured: false`. The four
controlled-position values are not secrets — they are committed defaults
(`docket/hire/catalogue.py` worked example, and the `docket-lp-record.service` ExecStart) — so they
were set: wallet `0xe558…c946`, token id `7141050`, declared value `50.55`, recenter cost `1.00`.
`DOCKET_CANARY_PRIVATE_KEY_FILE` remains unset and owner-supplied.

Run 9 (`17:43:29Z` → `17:43:34Z`) verdict `failed`:

| Leg | Result |
|---|---|
| `fresh_browser_surface` | passed — HTML over HTTPS, one same-origin script, no cookies |
| `snapshot_age_surface` | passed — snapshot 5, age 181 s |
| `free_verified_example` | passed |
| `controlled_live_lp` | **failed — `measured_value_incomplete`** |
| `exact_0_50_settlement`, `complete_human_result`, `proof_binding`, `rejected_replay` | `not_yet_exercised` — `decision_grade_free_preflight_failed` |

This is the canary working, not a regression. The hire returns HTTP 200 with a real diagnosis; what
is incomplete is the measured-value block, which is empty because the preregistered v3 paired report
has not run. The canary therefore refuses to call the service decision-grade, and Range Doctor
cannot enter paid stock until v3-01 produces a paired benchmark. That coupling is deliberate.

### Live surfaces, checked from outside the host

`/health`, `/stats`, `/services`, `/compare`, `/lp-record`, `/pancake`,
`/registrations/range-doctor.json`, `/advantage/v3.json` all returned 200 over HTTPS.
`/lp-record` served the real journal — 8 lines, `2026-08-15T21:41:39Z` through
`2026-08-22T06:03:14Z`, `skipped_unparsable` 0, `truncated` false. Body digests at collection time:
`/stats` `6328b104097752cc…`, `/services` `f86f736e8793f360…`, `/pancake` `c2d89e9a67f5ccde…`,
`/lp-record` `42a17f56122a3d06…`. All four category services report a non-empty `metrics` list and
an `evidence_modality`. Neighbouring vhosts (`warden`, `tilla`, `beacon`, `solvent`) answered 200
before and after; nginx was never reloaded.

### What this evidence does not establish

- `v3-04-warden-security` is `complete_unscored` with `score_sheets_missing`: all 24
  primaries are terminal (23 succeeded; manual `w4-ho-01` failed), but seat B returned no
  first scoring response and the registered rule forbids retry or substitution. The ledger
  proves `invoke_error` / `JSONDecodeError`; the operator's contemporaneous account says a
  crib sheet absent from this repository led to payload text being pasted instead of the
  required JSON answer object. Read-only frozen-label formulas show Warden recall 0.50
  versus manual 0.75 and three Warden critical failures. Missing rubric medians prevent a
  complete registered falsifier evaluation. At the 2026-08-28 committed-artifact
  observation, v3-02 and v3-05 are `locked_not_run`, with locked inputs and no claimed
  primaries; v3-01 and v3-03 remain `superseded_before_input_lock`.
- No settlement has occurred and no service is in paid stock.
- The rehearsal proved only the mechanism at a scratch moment. The later registered Yield and Range
  captures completed on their first scheduled attempts and their inputs are now locked, but neither
  family has a claimed primary or result in this committed observation.
- Every figure above was collected by the builder. It is consistent with the tree and the running
  process, which is the property a reader can test; it is not independent.

---

## Collected 2026-08-28 — four category-service ERC-8004 identities

All four identities are in the BSC mainnet ERC-8004 registry
`0x8004a169fb4a3325136eb29fa0ceb6d2e539a432` (chain ID 56). At the recorded observation,
`ownerOf` returned `0xe55816904796341bf8535e25f6c8b647927fc946` for every identity.

| Service | Agent | Mint block | Block time (UTC) | Registration transaction | Token URI |
|---|---:|---:|---|---|---|
| Range Doctor | 311253 | 118559596 | `2026-08-28T10:28:20Z` | `0x032a4b1921e2b2dc44f46e24461623be3802f508ba429f5acd0380de5ce688c1` | `https://docket.gudman.xyz/registrations/range-doctor.json` |
| Grid Operator | 311255 | 118559736 | `2026-08-28T10:29:23Z` | `0x991d905b0e55093f4c55ceff0d8deed68d45af2036b08e0ba13e87cbdbde850b` | `https://docket.gudman.xyz/registrations/grid-operator.json` |
| Yield Router | 311257 | 118559820 | `2026-08-28T10:30:01Z` | `0x3d490b9326079cabce9ee36ab64981d23da1d46a8e370b48e73382126671e9b0` | `https://docket.gudman.xyz/registrations/yield-router.json` |
| Health Guard | 311259 | 118559871 | `2026-08-28T10:30:24Z` | `0x7f7ffd402d54d4284de6a1ecbffc8f43d07c5a8f522f6b5507d90dd9302ec531` | `https://docket.gudman.xyz/registrations/health-guard.json` |

The checks read `ownerOf` and `tokenURI`, decoded the registry's `Registered` event, and read
each mint block timestamp. Two public BSC RPC providers independently returned the same chain ID,
owners, token URIs, and block timestamps. The normalized facts are committed in
[`erc8004-category-identities.json`](erc8004-category-identities.json), and an offline test binds
that evidence to the service registry and committed registration documents.

### What this identity evidence does not establish

An ERC-8004 identity is a registration, not an endorsement, evidence of paid stock, or evidence
that a service produced a result. Ownership can change after the recorded observation. This
collection is chain evidence, not proof that the newer service bindings have been deployed.
`warden-scan` remains unbound.

---

## Collected 2026-08-30 — approved settlement canary and current state

The owner approved one Range Doctor payment canary. Public canary run 18 started at
`2026-08-30T11:23:35.359953Z`, finished at `2026-08-30T11:23:45.200371Z`, and passed all
eight legs: fresh browser surface, snapshot-age surface, free verified example, controlled
live LP, exact 0.50 settlement, complete human result, proof binding, and rejected replay.

The settlement leg records `500000000000000000` atomic units of BSC USDT, payment id
`0xcaafa68fef0e0b0691b1afcd7d7dd8a0827d04a897e8a01fa193d67bf6338fcb`, and transaction
`0x0a036066db0ccbde6eeb8d333e5747e549a61f251935fe8abceaf13b681a1258`. The identical
signed request was rejected with HTTP 409 and `authorization_replay`. The 18-run public
history contains exactly one check whose settlement observation says `settled: true` and
exactly one check whose replay observation says `identical_request_rejected: true`.

This proves one owner-operated private-canary payment lifecycle. The public record reports
the facilitator transaction; by itself it is not an independent chain-finality proof and it
does not open public paid inventory. The live `/services` response still reports
`paid_stock=false` for all six services. Only Range Doctor's `cold_canary` limb is true;
its `fresh_paired_benchmark` and `true_settlement` limbs were false in the public API
observed from the still-deployed `b8b6ed7` runtime. The reviewed post-canary source changes
Range Doctor's static `true_settlement` limb to true, but `fresh_paired_benchmark=false`
still keeps paid stock closed. That source is not deployed in this record. The recurring
`docket-canary.timer` was separately read from the host as disabled and inactive.

The live v3 report contains six families: `v3-01-range-doctor` and
`v3-03-warden-security` are `superseded_before_input_lock`;
`v3-02-yield-router` is `abandoned_after_failed_primary`;
`v3-04-warden-security` is `complete_unscored`; `v3-05-range-doctor` is
`locked_not_run`; and `v3-06-yield-router-assisted` is
`registered_waiting_for_inputs`.

The deployed runtime identifies commit
`b8b6ed76313dc6b469a3edd1f988256a818bde3b`. At collection time, local `main` and
`origin/main` identified `3b9e03715af9fd973b85cefec891b1e97cba85a5`, the base of this
documentation update. That source-only commit after the deployed runtime does not turn this
builder-collected record into an independent observation.

---

## Collected 2026-09-02 — release of 4a632c0

The owner approved one release. `4a632c0` was built from a clean worktree, shipped, and
released to `docket.gudman.xyz`; the prior tree is retained at
`/opt/docket.bak-20260902T144652Z`.

Release gates. GitHub Actions was already green on this exact commit for `test (3.11)`,
`test (3.12)`, and `package` — the CI `test` job runs `pytest -q` and the `package` job
reproduces the runtime lock, builds the clean-HEAD bundle, installs the wheel into a venv
outside the checkout, and runs `smoke_installed.py`. Those Linux results, not a Windows
run, are what this release rests on. The builder additionally reproduced locally:
`node --check docket/api/web/app.js`; `uv export` against `uv==0.11.16` with no diff to
`deploy/runtime-requirements.txt`; the bundle build and its own `verify`; a fresh
out-of-checkout venv install with `pip check` clean; and `smoke_installed.py` exit 0.
`preflight.sh 22` passed — the operand is the host's live `nginx -t` `[warn]` count, which
was independently measured at 22 before the run, with 888,959,812 KiB free under `/opt`
and all thirteen tracked units verified. `install-canary.sh` ran first and backed up its
prior targets to `/var/backups/docket-canary/20260902T144452Z`, leaving the payment-bearing
timer disabled and inactive.

Deployed identity, read back from the host after the release:

| Field | Value |
|---|---|
| `RELEASE-commit.txt` | `4a632c01ebcfdccaed36e642cec2e74adbb69381` |
| `.venv` target | `/opt/docket-venvs/4a632c01ebcf` |
| Wheel SHA-256 | `923d410953e11bd98cec7dc9d26ef371ccd6e5c73bb8f11d3ce964c32b3769b6` |
| Runtime-lock SHA-256 | `2b0fb7bc65a54cb8a648155108cbda3a920b40397f02b1f1fd0d8007cf14d33c` |
| `docket.service` | active |

The runtime-lock digest is identical to the previous release, so no dependency moved. The
six timers were restored to their captured states: `docket-lp-record`, `docket-refresh`,
`docket-v3-capture`, `docket-v3-range-capture`, and `docket-v3-yield-v6-capture` are each
`enabled` and `active`; `docket-canary.timer` remains `disabled` and `inactive`.
`docket-v3-yield-v6-capture.timer` still reports
`NextElapseUSecRealtime=Thu 2026-09-03 13:50:00 CEST`, unchanged by the release.

Observed from outside the host after the release, eight public routes returned 200: `/`,
`/stats`, `/advantage`, `/services`, `/service?id=range-doctor`, `/hire`, `/lp-record`,
and `/canary`.

The six v3 family states are unchanged by this release: `v3-01-range-doctor` and
`v3-03-warden-security` `superseded_before_input_lock`; `v3-02-yield-router`
`abandoned_after_failed_primary`; `v3-04-warden-security` `complete_unscored`;
`v3-05-range-doctor` `locked_not_run`; `v3-06-yield-router-assisted`
`registered_waiting_for_inputs`.

`/services` reports `paid_stock=false` for all six services. Range Doctor's admission limbs
are `fresh_paired_benchmark=false`, `cold_canary=false`, `decision_grade_presenter=true`,
`true_settlement=true` — the single behavioural change a reader can observe from this
release. `cold_canary` is false because the canary timer is disabled and run 18 is older
than the 36-hour freshness limit, not because run 18 failed.

At this observation the public repository, `origin/main`, and the deployed runtime all
identify `4a632c01ebcfdccaed36e642cec2e74adbb69381`.

Repository settings completed the same day, closing steps 11, 13 and 14 of
[`publication-checklist.md`](publication-checklist.md), which had not been performed after
the visibility conversion: the repository website is set to `https://docket.gudman.xyz/`
with a description; a `main` branch ruleset named `main protection` is active, blocking
deletion and non-fast-forward pushes and requiring `test (3.11)`, `test (3.12)` and
`package`; secret scanning and push protection are enabled.

### What this record does not establish

Every figure above was collected by the builder from the host it deployed to. It is
consistent with the tree and the running process, which is the property a reader can test;
it is not independent. CI is the one part of this record produced by a system the builder
does not control.

---

## Collected 2026-09-05 — marketplace release of c5e6163

The owner approved the marketplace release. Commit
`c5e6163eb05f54b406731c05a3fdc9fd4de020a2` was built from a clean detached worktree,
shipped as `docket-0.1.0-py3-none-any.whl`, and released to `docket.gudman.xyz`.

Release identity, read back from the host after the release:

| Field | Value |
|---|---|
| `RELEASE-commit.txt` | `c5e6163eb05f54b406731c05a3fdc9fd4de020a2` |
| `.venv` target | `/opt/docket-venvs/c5e6163eb05f` |
| Wheel SHA-256 | `8997774d43de32825cbfe91fef6da8a53366983fcd7a0ea65f4f7f4fd29cb464` |
| Runtime-lock SHA-256 | `2b0fb7bc65a54cb8a648155108cbda3a920b40397f02b1f1fd0d8007cf14d33c` |
| Release-manifest SHA-256 | `9157bf43b326cc1704b364fb2cda01d7e7050d10d9650c4e2f2ac3aa6f604f7d` |
| Database backup | `/var/backups/docket/agents-20260904T225814Z.sqlite3`; mode `0600`, owner `root:root` |
| `docket.service` | active |

GitHub Actions run `33927181234` completed successfully on the exact release commit. Its
six jobs were `audit`, `lint`, `package`, `e2e`, `test (3.11)`, and `test (3.12)`. The
builder also reproduced the `uv==0.11.16` runtime lock without a diff, built and verified
the clean-HEAD bundle, installed its hash-pinned wheel into an external venv, ran
`pip check`, ran the installed smoke test, checked the browser JavaScript, and checked the
Bash syntax. On the host, the secure-owner bundle verifier and `preflight.sh 22` passed;
the preflight recorded 22 existing nginx warnings, 888,746,928 KiB free under `/opt`, and
all 21 tracked units verified.

Two earlier attempts rolled back automatically before this release completed. The
`4d5d744` attempt reached a false CSS failure because the static smoke used a short-circuiting
`grep -Fq` pipeline under `pipefail`; pull request 3 changed that check to drain the response.
The `c983048` attempt then found a real release-boundary defect: the four identity files in
the new venv were mode `0640` and owned by `root:root`, so the `docket` process could not
read them. Pull request 4 made their final mode explicitly `0644`. The failed trees remain
at `/opt/docket.failed-20260904T214654Z-4d5d744cc6fc` and
`/opt/docket.failed-20260904T223406Z-c983048681bc`; their database backups remain at
`/var/backups/docket/agents-20260904T214654Z.sqlite3` and
`/var/backups/docket/agents-20260904T223406Z.sqlite3`.

The public marketplace surfaces contain exactly six services: `grid-operator`,
`health-guard`, `range-doctor`, `solvent-signal`, `warden-scan`, and `yield-router`. The
four declared categories are `rebalancing`, `grid_trading`, `yield_optimisation`, and
`health_factor`, each with one assigned service. Every service reports `paid_stock=false`.

The nine v3 family states observed after the release were:
`v3-02-yield-router` is `abandoned_after_failed_primary`;
`v3-04-warden-security` is `complete_unscored`; `v3-05-range-doctor` is `locked_not_run`;
`v3-06-yield-router-assisted`, `v3-07-range-doctor`, `v3-08-yield-router`, and
`v3-09-health-guard` are `registered_waiting_for_inputs`; `v3-01-range-doctor` and
`v3-03-warden-security` are `superseded_before_input_lock`.

Nine non-payment timers were enabled and active: `docket-jobs`, `docket-lp-record`,
`docket-probe`, `docket-refresh`, `docket-v3-capture`, `docket-v3-range-capture`,
`docket-v3-range-v7-capture`, `docket-v3-yield-v6-capture`, and
`docket-v3-yield-v8-capture`. The payment-bearing `docket-canary.timer` remained disabled
and inactive. The two future registered timers retained their exact schedules:
`docket-v3-range-v7-capture.timer` at `2026-09-05 11:50:00 UTC`, ahead of the v3-07
12:00/12:01/12:02 capture attempts, and `docket-v3-yield-v8-capture.timer` at
`2026-09-06 11:50:00 UTC`, ahead of the analogous v3-08 capture.

At `2026-09-05T06:07Z`, `/api/status` was `degraded` only because the refresh candidate
started at `2026-09-05T01:41:08Z` had ended in an upstream read timeout without becoming a
complete snapshot. Candidates 58 and 59 each stored exactly 400 of 473 expected agents and
failed on the next filtered 8004scan page, at offset 400; a direct host probe of that exact
page later timed out after 35.001 seconds with no response bytes, while the offset-300
control returned HTTP 500 after 10.264 seconds. The last complete snapshot, observed at
`2026-09-04T13:42:45Z`, remained served; the next ordinary refresh was scheduled for
`2026-09-05T07:41Z`. Database reachability and the archive RPC check were healthy. This is
an as-of record of an external outage, not a statement that the outage continued later.

### What this record does not establish

Every host, endpoint, timer, and artifact observation above was collected by the builder.
The exact-commit GitHub Actions result is independently hosted, but the deployment record
is not a signed or independently anchored attestation. The current runtime identity remains
`c5e6163eb05f54b406731c05a3fdc9fd4de020a2` even when a later source-only documentation
commit records it.
## Collected 2026-09-05 — probe-fix release of e35b647

Commit `e35b64776bc9d3a1dbe7700917e195c006e7d800` was built from a clean detached worktree,
shipped as `docket-0.1.0-py3-none-any.whl`, and released to `docket.gudman.xyz` at
`2026-09-05T14:00:56Z`. It carries two merges over `c5e6163`: pull request 8, which makes the
production probe ask `/` for HTML, and pull request 7, which commits the v3-07 enumerable
frame and names it in the source manifest. No other code changed.

Release identity, read back from the host after the release:

| Field | Value |
|---|---|
| `RELEASE-commit.txt` | `e35b64776bc9d3a1dbe7700917e195c006e7d800` |
| `.venv` target | `/opt/docket-venvs/e35b64776bc9` |
| Wheel SHA-256 | `6f412c8e3927048a0a33b37b8ff80425ecb2dc0d5ba2b4b76df068d4b02f5e7c` |
| Runtime-lock SHA-256 | `2b0fb7bc65a54cb8a648155108cbda3a920b40397f02b1f1fd0d8007cf14d33c` |
| Release-manifest SHA-256 | `f14596e966f5e440ddc03fcf6e179912327300f7a3126cb464450019a4e734ed` |
| Database backup | `/var/backups/docket/agents-20260905T140056Z.sqlite3` |
| `docket.service` | active |

GitHub Actions run `33970180194` completed successfully on the exact release commit, all six
jobs. The runtime-lock digest is unchanged from the previous release, so this release moved
no dependency. The builder reproduced the `uv==0.11.16` runtime lock without a diff, and the
wheel digest matched on the workstation and on the host before the release ran. On the host,
`preflight.sh 22` passed against a freshly re-derived count of 22 existing nginx warnings,
887,030,440 KiB free under `/opt`, and all 21 tracked units verified. The release completed
on its first attempt.

### What this release corrects

Every production probe run since the marketplace release had failed — 91 of 91 in the
24 hours before this release — and the public status page read `degraded` over a shell that
was serving fine. The probe's first step fetched `/` with no `Accept` header. That route
negotiates on `Accept` and answers a bare `GET` with the JSON index, which carries no title,
so the step's title check failed while the other four steps passed. The step now asks for
`text/html`, and the probe's test fixture negotiates the same way the real route does, so a
probe that forgets the header fails the test rather than production.

A probe run started by hand at `2026-09-05T14:01:39Z` under the released code passed all
five steps: `home`, `services`, `api_status`, `advantage_v3`, and `free_tier_hire`. It is the
first `ok` row in `probe_runs` since the marketplace release. The run the timer fired at
`2026-09-05T14:00:07Z`, during the service swap itself, failed and is recorded as such.

### What remained degraded, and why

At `2026-09-05T14:02Z`, `/api/status` still read `degraded`. Two readings held it there,
neither of them this deployment's:

- The probe window. Three recent runs are considered and one had passed; the reading clears
  on its own after two more ten-minute ticks under the released code.
- The registry refresh. The last complete snapshot was observed `2026-09-04T13:42:45Z`, and
  the candidate begun `2026-09-05T07:41:29Z` died within a minute on `HTTPStatusError: 500
  from /agents`; the attempt before it ended in a read timeout. A direct request to
  `https://8004scan.io/api/v1/agents` from the workstation at `2026-09-05T13:40Z` returned
  HTTP 500 after 12.6 seconds. This is an external outage of the upstream registry, and the
  status page is reporting it correctly. The next scheduled retry runs every six hours.

The nine v3 family states, the six services, the four categories, and `paid_stock=false` on
every service were unchanged by this release. The v3-07 capture registered for
`2026-09-05T12:00:00Z` had already fired and succeeded at attempt 1 before this release, and
its timer shows no further scheduled run; `docket-v3-yield-v8-capture.timer` remains armed
for `2026-09-06 11:50:00 UTC`. Nine non-payment timers are enabled and active; the
payment-bearing `docket-canary.timer` remained disabled and inactive.

### What this record does not establish

It does not establish that the upstream registry recovered, that the probe window cleared,
or that any paid path was exercised. It is an as-of record of one release and the first
probe run under it.

## Collected 2026-09-05 — release of 1d0d27c and the first real activations

### The release

Commit `1d0d27c8e0dd07c46a6449a04405c8456019d4a7` was released to `docket.gudman.xyz` at
`2026-09-05T18:20:44Z`. It carries two merges over `e35b647`: pull request 10, which lets
every service be activated whatever it costs, and pull request 11, which drains the homepage
and status-page smokes the way the stylesheet smoke already did.

| Field | Value |
|---|---|
| `RELEASE-commit.txt` | `1d0d27c8e0dd07c46a6449a04405c8456019d4a7` |
| Wheel SHA-256 | `9aafbed979dc011915eb2f6945c3decd0f702213d6c0ddf94c3359f957c86d50` |
| Runtime-lock SHA-256 | `2b0fb7bc65a54cb8a648155108cbda3a920b40397f02b1f1fd0d8007cf14d33c` |
| Release-manifest SHA-256 | `bd4528a485f4336c8fddfc1081938d6cf07dce10e8caa32d71db14c9491a54df` |
| Database backup | `/var/backups/docket/agents-20260905T182044Z.sqlite3` |
| CI | run `33983375163`, all six jobs, on the exact commit |

An attempt to release `15f4029` — pull request 10 alone — at `2026-09-05T17:55Z` was refused
by the homepage smoke and rolled back automatically, with the title on screen: the smoke
piped curl into a quiet grep, which exits on its first match and closes the pipe, and curl's
write error then failed the pipeline under `pipefail`. That is the shape pull request 3 had
fixed in the stylesheet smoke; pull request 11 fixed the two page smokes the same way, and the
fake curl in `tests/test_release_scripts.py` now pads the pages so the drain test covers all
three. The failed tree remains at `/opt/docket.failed-20260905T175506Z-15f402946688`. The
runtime-lock digest is unchanged, so neither release moved a dependency.

### What pull request 10 corrected

Opening `/activate?service=range-doctor` on the live site in a real browser showed, for every
service, exactly two buttons: *Try free sample* and *Use the worked example*. The activation
control rendered only when the catalogue said `paid_stock`, and until a service's canary
passes it never does. So no service could be activated from the browser — not a one-shot,
not a session — and the activation backend, the session keys, the executors and the jobs
timer running every minute had no front door. The production `activations` table held zero
rows from the marketplace release until this one.

The catalogue card says whether a service can be paid for; the server prices the activation.
A one-shot on an unadmitted service is quoted on the free tier, and the API's contract for it
is create, then approve, and the service runs. A session is quoted free whatever the stock,
because it is funded rather than bought. The control now renders in every case, labelled
*Activate and pay 0.50 USDT*, *Activate on the free tier*, or *Activate Range Keeper as a
session*, and a free-quoted one-shot approves and runs instead of asking for payment terms
that do not exist.

### The first real activations

Each of these was made against the live site through the deployed page in a real Chromium,
with a wallet created fresh for the run — a real secp256k1 key signing real EIP-191 messages —
and with no request faked. Nothing was funded and nothing was spent: every activation was
quoted on the free tier, which is what production quotes while no service is admitted.

| Activation | Kind | Owner | Outcome |
|---|---|---|---|
| `act_526632dd00c17c8d20e08103` | one-shot | `0x1953b16768d794c7fb8df52bD2E089BDe81Bb5bb` | `completed` at `2026-09-05T18:21:45Z` with a result and a receipt |
| `act_2b828b0c4fc7e31b64e942c6` | session | `0x94e3593Aca077ce30595B12f1aF2905d376c2253` | key `0x99D1dA41d133CA6631bBcD17821b32CE39Fdfb80` minted by the jobs process; revoked from *My agents*; `revoked` after the sweep read every balance zero |

The one-shot made exactly three API calls — the nonce, the create, the approve — and none to
`/hire`. Its receipt carries `input_hash`
`0x6062644dc43f07c4eb978ccc507e09cb1d5d0530db4e5e248fd27fca2600257b` and `output_hash`
`0x319bbb19c950bfdedc79152e9be5ce1f9dc24832e559b12be43741244ee9e13f`, recomputable as
described under "Recomputing the hashes yourself". The page rendered the record with its
price and permissions, the choice of once or continuously, the inputs, the progress log, the
state rail through every transition, the result, and the receipt with copy and download.

The session's trail, as the API returns it: `quoted → awaiting_wallet` (user) →
`authorized` (the create signature recovered to the owner) → `awaiting_session` (the job
runner will create the key on its next pass) → the key `0x99D1dA41…` was created, holding
only what the owner funds it with → `revoking` (the owner revoked from *My agents*; the float
is swept and verified before this closes) → `revoked` (chain: every balance read zero after
the sweep). The *My agents* row showed the permission scope in full — per-token caps, the
BNB cap, slippage, the gas ceiling, seven contracts, the expiry — and withdrew its controls
while the sweep was in flight. The web process never held the session key: the
`awaiting_session` wait is the jobs process minting it.

Two further session rows, `act_b9e115c56f476e737efd2b4a` and
`act_52d31ad209db8f8b2348290f`, were opened by earlier runs of the same walk-through whose
throwaway keys were not kept, so their owners can never act on them; `act_b9e115…` also had
its key minted. They sit in `awaiting_session` until their expiry. A third,
`act_402227d8c37da77b164451f9`, was revoked before its key was minted and closed `revoked`
the same way. None holds anything.

### What remained degraded

At `2026-09-05T18:35Z`, `/api/status` read `degraded` for the registry refresh only: the
upstream 8004scan API was still returning HTTP 500. The probe window read three of three
recent runs passing.

### What this record does not establish

It does not establish the paid path through an activation — no service is in paid stock, so
no activation could be quoted `x402-exact` — nor a funded session executing on chain. It
establishes that the journey the page offers runs end to end on the live site for a real
wallet: open, sign, run, receive a result and a receipt; or open a session, have its key
minted, and revoke it with the sweep verified.

