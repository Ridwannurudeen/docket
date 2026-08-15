# Source and deployment manifest

## Status

This document separates what is present in source from what has not been deployed or
externally anchored.

| Field | Value |
|---|---|
| Package | `docket` |
| Version | `0.1.0` |
| Python | `>=3.11`; CI uses 3.12 |
| Application factory | `docket.api:create_app` |
| Builder base commit | `731dcb3d3fe1267546c96fd73118a3b34d58b7b3` |
| Release source commit | `bcccafea9b461889ae2fbed7086c827ce1fe7386` — remote-reachable, see below |
| Release wheel digest | `ddc128bacf689840ee0845e58bcb05d5bef92b760a92161e89ae1ee14784b91b` |
| Public repository visibility action | Not performed; owner-only |
| Deployment action | **Performed 2026-08-15T05:17:06Z** to `docket.gudman.xyz` |
| Deployed source/wheel identity | The wheel above, imported from site-packages — see "Deployed identity" |
| Live settlement transaction | Missing. Settlement is built, disabled, and has never run. |

The base commit identifies the tree before the public-package change. It does not identify
the release and must not be used as a deployment hash.

## Deployed identity (recorded 2026-08-15)

| Field | Value |
|---|---|
| Deployed at | `2026-08-15T05:17:06Z` |
| Runtime venv | `/opt/docket-venvs/bcccafea9b46` (permanent path; `/opt/docket/.venv` is a symlink to it) |
| Runtime `docket.__file__` | `/opt/docket-venvs/bcccafea9b46/lib/python3.12/site-packages/docket/__init__.py` |
| Python | 3.12.3 · `pip check` clean |
| Previous release backup | `/opt/docket.bak-20260815T051706Z` (retained) |
| Database backup | `/root/docket-db-backups/agents-20260815T051706Z.sqlite3`, 45,240,320 bytes, `PRAGMA integrity_check` = ok, 3 snapshots, taken with the app stopped and **before** the additive `stop_reason` migration ran |
| Canary units | `docket-canary.service` + `.timer` installed and enabled; first record `not_yet_exercised` |

**Why the wheel digest may now be called the deployed artifact.** Before this release the host
ran an *editable* install — `__editable__.docket-0.1.0.pth` resolved `docket` to
`/opt/docket/docket`, the source tree, so no wheel was the runtime artifact and claiming one
would have been false. This release installs the wheel into a fresh venv at a path that does
not move, and the runtime import path above was read from the live interpreter after cutover.

## Remote reachability, and exactly what it witnesses

**Pushed 2026-08-15.** `origin/docs/deliberation-round2` contains both the v3 stage-one
registration `88cc2bc` and the release commit `bcccafea9b46`. GitHub recorded the ref creation
at **`2026-08-15T06:08:36Z`**, matching `repo.pushed_at`. That timestamp is GitHub's and cannot
be set by this repository's authors.

What that does and does not establish, stated precisely because the v3 specs rest on it:

- **It does establish** that this content existed by 2026-08-15T06:08:36Z, attested by a third
  party. A commit backdated after that moment can no longer be silently inserted *before* the
  registration, which is the specific forgery the audit demonstrated against the unpushed chain.
- **It does not establish** that the commits were authored when their headers say. Committer
  dates are still set locally, and branch protection is unavailable on a private repository —
  the API answers `Upgrade to GitHub Pro or make this repository public` — so the ref can still
  be force-pushed by its owner.
- **What would close the gap:** an OpenTimestamps proof over the stage-one protocol hash, which
  is Bitcoin-anchored, works on a private repository, and is checkable by a stranger with no
  GitHub account. Not yet done.

The repository remains **private**. Public accessibility during Sep 9-23 judging is an owner
action and a stated eligibility condition.

## Source roots

| Root | Contents | Shipped in wheel |
|---|---|---|
| `docket/` | Runtime package, API, services, evidence builders, packaged artifacts | Yes |
| `experiments/` | Read-only/simulation helpers and committed result JSON | Python package yes; result JSON stays at repository root except packaged evidence under `docket/` |
| `abis/` | Contract ABIs used by experiments/tests | No package-data rule |
| `tests/` | Source tests and installed-wheel smoke | No |
| `docs/` | Plans, audits, architecture, runbook, threat model, API/evidence docs | No |
| `data/` | Ignored runtime SQLite state | No |

## Explicit Python packages

`pyproject.toml` declares:

```text
docket
docket.advantage
docket.advantage.v2
docket.advantage.v3
docket.api
docket.agents
docket.agents.grid
docket.agents.pancake
docket.agents.venus
docket.agents.yield_router
docket.escrow
docket.execution
docket.hire
docket.marketplace
experiments
```

`tests/test_packaging.py` checks this list against every `__init__.py` package on disk and
names the four category packages separately. The CI package job tests the built wheel rather
than relying on this source-tree comparison alone.

## Package data

The wheel includes:

- API machine docs and browser assets under `docket/api/static/` and `docket/api/web/`.
- V1 experiment JSON.
- V2 corpora, specs, and runs.
- V3 stage-one specs.
- The MIT license in distribution metadata.
- The README as Markdown package metadata.

Setuptools currently warns that nine data-only directories look importable but are not in
the explicit package list. The package-data globs include their files today, and the
installed-wheel smoke loads the report and API from the built artifact. The warning remains
a backend-maintenance risk; this build does not hide it.

## Evidence artifact manifest

| Path | Exact-byte SHA-256 |
|---|---|
| `experiments/e1c-result.json` | `eae28a4b029b6c656afb82f244e591aaa859a35468e94188a0c762d1b9fb5dc4` |
| `docket/advantage/experiments/01-liquidity.json` | `c048e5ede594f4bb7055dcba871acf9c1c3a22bfd1100f5504377fa4f8394116` |
| `docket/advantage/experiments/02-trading.json` | `8735817bff88dc9b065f03fbdac7cefc5abaebbe28c94b16f9ebb4e9e90f4c17` |
| `docket/advantage/experiments/03-security.json` | `f4ad3c87b8cef5101dc1d1ed2e947b5012c7f77d0ff9d6d81cef1941b5c53f0c` |
| `docket/advantage/v2/corpus/liquidity/pools.json` | `f60b68ed4b7b4a04dec6f3772c9f8aab0955d0c1ad5d44397a16fddccfc015d5` |
| `docket/advantage/v2/corpus/security/payloads.json` | `11e9094f5a4a106d2f85be7a143c8c28ee6ee56c0521d1a0cda9672edab9f60a` |
| `docket/advantage/v2/corpus/series/bnbusdt-1h-2026-07.json` | `d642d970928d9ec45b228c047b4bc7fd99a62964515b68342c5eeb64c5003b72` |
| `docket/advantage/v2/specs/01-liquidity-arithmetic.json` | `72543e94358080b1daa9a349b99e48958e7fed2e0a0674d2ea0c11ae220cab50` |
| `docket/advantage/v2/specs/03-security-corpus.json` | `86c439c2f146db8dc2209fa006b0d3467ee8cb96d57711334c0ccda5852b5f5c` |
| `docket/advantage/v2/specs/04-grid-replay.json` | `2b22203c457edf86023c6574e8d2805fc819ff469bd3fc4b2c18068eb5adc84d` |
| `docket/advantage/v2/runs/01-liquidity-arithmetic.json` | `bcb4836197192cb275a4d520646ef2c4d345023dcc547cbdb2d7a5afe10f35a7` |
| `docket/advantage/v2/runs/03-security-corpus.json` | `b67f0d3c1b923065c505705fe3358d0e7dacb64e6c15da4d0d33f2896afa34f0` |
| `docket/advantage/v2/runs/04-grid-replay.json` | `7a81088a5b7189c5b260e0957e1221b2557711bc8f71f934515b0dbc82128af4` |
| `docket/advantage/v3/specs/v3-01-range-doctor.json` | `4299b50810398510a693aa10c503a592e65d5ee9fa6339548d248aac57449a0c` |
| `docket/advantage/v3/specs/v3-02-yield-router.json` | `9516cdd8f883235f7f2ae5268fc6c9b026489529ba6a1a2efb09fd12ab647221` |
| `docket/advantage/v3/specs/v3-03-warden-security.json` | `01b0e9d13b4302b8e2fa97021eafd89de1f22bbc6f9afadfadb041e54e787645` |

## Deployment record required for parity

A future deploy record must contain, without inference:

1. Release commit reachable from the stated remote.
2. Exact wheel filename and SHA-256.
3. Python and resolved dependency versions.
4. Process definition and working directory.
5. Static asset digests and backend artifact digest.
6. Database snapshot ID/population/coverage served at process start.
7. Settlement enabled/disabled state with credential values omitted.
8. Deployment time and read-only canary results.
9. Rollback wheel/digest and database-backup time.

Until those fields exist as a signed or externally anchored record, the correct deployment
statement is: **not established from this repository**.
