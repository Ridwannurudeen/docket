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
evidence only: neither input is locked, no arm has run, and no result exists. The retired 2026-08-21
timer was removed by the release.

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
  complete registered falsifier evaluation. v3-02 and v3-05 still wait for inputs; v3-01
  and v3-03 remain superseded.
- No settlement has occurred and no service is in paid stock.
- The rehearsal proved only the mechanism at a scratch moment. The later registered Yield and Range
  captures completed on their first scheduled attempts, but they are inputs only: neither input is
  locked, no arm has run, and no result exists.
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
