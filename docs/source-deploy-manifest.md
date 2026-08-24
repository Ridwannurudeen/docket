# Source and deployment manifest

## Status

This document separates source state, the builder-collected deployment record, and what
remains unanchored.

| Field | Value |
|---|---|
| Package | `docket` |
| Version | `0.1.0` |
| Python | `>=3.11`; CI uses 3.12 |
| Application factory | `docket.api:create_app` |
| Builder base commit | `731dcb3d3fe1267546c96fd73118a3b34d58b7b3` |
| Release source commit | `534af826575a3c316eaace03b5e41ab077d4c253` — remote-reachable from `origin/docs/deliberation-round2`, see below |
| Release wheel digest | `b8c9a257c9ab3acab111b87d2507153b7d0a7bd54a41ef9110a2a57c88758beb` |
| Public repository visibility action | Not performed; owner-only |
| Deployment action | **Recorded as performed 2026-08-16T12:20Z** to `docket.gudman.xyz` |
| Deployed source/wheel identity | Builder-collected commit and wheel record — see "Deployed identity" |
| Live settlement transaction | Missing. Settlement is built, disabled, and has never run. |

The base commit identifies the tree before the public-package change. It does not identify
the release and must not be used as a deployment hash.

## Deployed identity (recorded 2026-08-16)

The builder collected the following values from the host after the 12:20Z deploy and
committed them to `docs/operational-evidence.md`:

| Field | Value |
|---|---|
| Recorded at | `2026-08-16`, refreshed after the `12:20Z` deploy |
| Host | `docket.gudman.xyz` |
| `/opt/docket/.venv` resolves to | `/opt/docket-venvs/534af826575a` |
| `RELEASE-commit.txt` | `534af826575a3c316eaace03b5e41ab077d4c253` |
| Wheel SHA-256 | `b8c9a257c9ab3acab111b87d2507153b7d0a7bd54a41ef9110a2a57c88758beb` |
| Services recorded active | `docket.service`, `docket-lp-record.timer`, `docket-v3-capture.timer` |

`git cat-file -t` and `git rev-parse` resolve the recorded commit in this repository, and
the remote branch contains it. This makes the collector's record internally checkable; it
does not turn the record into an independent observation of the host.

## Remote reachability, and exactly what it witnesses

**Reachability checked 2026-08-22.** `origin/docs/deliberation-round2` contains both the v3
stage-one registration `88cc2bc` and deployed release commit `534af826575a`. GitHub recorded
the ref at **`2026-08-15T06:08:36Z`**, matching the previously collected `repo.pushed_at`.
That timestamp covers content pushed by that moment; it is not a timestamp for the later
deployed release commit.

What that does and does not establish, stated precisely because the v3 specs rest on it:

- **It does establish** that the content present in the ref at the recorded push existed by
  `2026-08-15T06:08:36Z`, and the current remote ref contains the registration commit.
- **It does not establish** when individual commits were authored. Committer dates are set
  locally, and the repository owner can rewrite the private remote ref.
- **What would close the gap:** an external timestamp or chain commitment over the stage-one
  protocol hash, recorded before inputs or runs. Not yet done.

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
- V3 stage-one specs, served report shell, and any JSONL ledgers, nested score sheets, or
  mappings present in the source tree.
- The MIT license in distribution metadata.
- The README as Markdown package metadata.

Setuptools currently warns that data-only directories look importable but are not in
the explicit package list. The package-data globs include their files today, and the
installed-wheel smoke loads the v3 report, page, machine docs, and API from the built
artifact. The warning remains a backend-maintenance risk; this build does not hide it.

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
| `docket/advantage/v3/specs/v3-01-range-doctor.json` | `2146cbf9c7886f3d1059d496f0469d3fcff01aed1e18e5fb48813c7a4421826f` |
| `docket/advantage/v3/specs/v3-02-yield-router.json` | `1292fbf63c0616a983b41cee7a3e727c867c78f12d01adbab576d45d5f85e15d` |
| `docket/advantage/v3/specs/v3-03-warden-security.json` | `d18270a88d0bfcd4d2fae807824427d117e7a1d6440317afd5b8a519cd1e9771` |
| `docket/advantage/v3/specs/v3-04-warden-security.json` | `8580781636f19b30b35d6478562cc9bec446407cc9c982bdc540b85e984546f7` |
| `docket/advantage/v3/sources/warden-v4-vendor-snapshot.json` | `8db24277dea2154e15f0b8e0f70941dfc62494f501b21fb838733e0b5a046bf7` |
| `docket/advantage/v3/sources/warden-v4-calibration-set.json` | `68850351a675ef6a6f0293d9108112318b42324477c6f87cbb2fe41841d5e55b` |
| `docket/advantage/v3/sources/warden-v4-heldout-cases.json` | `a06795b6c2eabbd0581be61cd26c5ed163eb406c5b958885e32c06834b658df7` |
| `docket/advantage/v3/provenance/warden-v3-03-pilot.json` | `8ed4c761e10c590da88c04764536d791ab5c3f2aa68d0945378c41f572cb99ef` |
| `W17-RECOMMENDATION.md` | `3f321533647a1689dadd80ddf9687c07c0e786f1970d4ad69a1b7e0db84b97c0` |

## Deployment record required for parity

A parity-complete deploy record must contain, without inference:

1. Release commit reachable from the stated remote.
2. Exact wheel filename and SHA-256.
3. Python and resolved dependency versions.
4. Process definition and working directory.
5. Static asset digests and backend artifact digest.
6. Database snapshot ID/population/coverage served at process start.
7. Settlement enabled/disabled state with credential values omitted.
8. Deployment time and read-only canary results.
9. Rollback wheel/digest and database-backup time.

As of 2026-08-16, the builder-collected record associates `docket.gudman.xyz` with commit
`534af826575a3c316eaace03b5e41ab077d4c253` and wheel SHA-256
`b8c9a257c9ab3acab111b87d2507153b7d0a7bd54a41ef9110a2a57c88758beb`. It is an
internally checkable as-of record, not a signed or externally anchored observation of the
host, and it covers no later commit.
