# Operational evidence — what is running, as opposed to what is written

The auditor of record runs under a read-only sandbox with no network. That is deliberate: an
auditor that could reach production could also change it, and its clearance would then be partly
a statement about its own edits. The cost is that it cannot check anything operational, so
several backlog entries were cleared "in code" and left open on deployment.

This file moves the legwork instead of loosening the sandbox. The evidence below was collected
by the builder from the two places the auditor cannot reach — the host and GitHub — and committed
so it can be audited under read-only like anything else.

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
