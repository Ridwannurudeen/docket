# Source and deployment manifest

## Status

This document separates source state, the builder-collected deployment record, and what
remains unanchored.

| Field | Value |
|---|---|
| Package | `docket` |
| Version | `0.1.0` |
| Python | Source requires `>=3.11`; current production runtime is Python `3.12.3` |
| Application factory | `docket.api:create_app` |
| Builder base commit | `731dcb3d3fe1267546c96fd73118a3b34d58b7b3` |
| Source base observed before this update | Local `main` and `origin/main` at `e35b64776bc9d3a1dbe7700917e195c006e7d800` |
| Current production release commit | `e35b64776bc9d3a1dbe7700917e195c006e7d800` |
| Current production wheel | `docket-0.1.0-py3-none-any.whl`; SHA-256 `6f412c8e3927048a0a33b37b8ff80425ecb2dc0d5ba2b4b76df068d4b02f5e7c` |
| Current production runtime-lock SHA-256 | `2b0fb7bc65a54cb8a648155108cbda3a920b40397f02b1f1fd0d8007cf14d33c` |
| Current production release-manifest SHA-256 | `f14596e966f5e440ddc03fcf6e179912327300f7a3126cb464450019a4e734ed` |
| Repository visibility | Public (verified 2026-09-02) |
| Current deployment record | Builder-collected 2026-09-05 from `docket.gudman.xyz`; see "Current deployed identity" |
| Historical deployment record | Builder-collected as performed 2026-08-16T12:20Z, 2026-08-30, 2026-09-02, and 2026-09-05 (`c5e6163`) to `docket.gudman.xyz`; preserved below and covers no later commit |
| Approved settlement canary | Run 18 settled exactly 0.50 USDT once and rejected the identical replay; all six services remain `paid_stock=false` |
| Recorded settlement transaction | `0x0a036066db0ccbde6eeb8d333e5747e549a61f251935fe8abceaf13b681a1258` — private canary evidence, not public paid inventory or independent finality proof |

The base commit identifies the tree before the public-package change. It does not identify
the release and must not be used as a deployment hash.

## Current deployed identity — builder-collected 2026-09-05 record (e35b647)

These values were read from the host's release identity files and interpreter. They are
builder-collected operational evidence, not a signed or independently anchored attestation.

| Field | Value |
|---|---|
| Host | `docket.gudman.xyz` |
| `RELEASE-commit.txt` | `e35b64776bc9d3a1dbe7700917e195c006e7d800` |
| Wheel filename | `docket-0.1.0-py3-none-any.whl` |
| Wheel SHA-256 | `6f412c8e3927048a0a33b37b8ff80425ecb2dc0d5ba2b4b76df068d4b02f5e7c` |
| Runtime-lock SHA-256 | `2b0fb7bc65a54cb8a648155108cbda3a920b40397f02b1f1fd0d8007cf14d33c` |
| Release-manifest SHA-256 | `f14596e966f5e440ddc03fcf6e179912327300f7a3126cb464450019a4e734ed` |
| Runtime Python | `3.12.3` |
| `.venv` target | `/opt/docket-venvs/e35b64776bc9` |
| Database backup | `/var/backups/docket/agents-20260905T140056Z.sqlite3` |
| Marketplace | Six services; four declared categories; nine v3 families; all six `paid_stock=false` |
| Non-payment timers | Nine enabled and active; v3-07 fired `2026-09-05 12:00 UTC` and succeeded, v3-08 armed for `2026-09-06 11:50:00 UTC` |
| Canary timer | disabled and inactive |

The runtime-lock digest is unchanged from the previous release, so this release moved no
dependency. GitHub Actions run `33970180194` passed all six jobs on the exact production
commit. This release changes one thing at runtime: the production probe asks `/` for HTML,
so the home step no longer fails on the JSON index. The first probe run under it, at
`2026-09-05T14:01:39Z`, passed all five steps. At `2026-09-05T14:02Z` `/api/status` still
read `degraded` for the probe window, which clears after two more passing ticks, and for the
registry refresh, whose upstream was returning HTTP 500 to a direct request; both are as-of
notes, not continuing-status claims. This release is recorded in
[`operational-evidence.md`](operational-evidence.md#collected-2026-09-05--probe-fix-release-of-e35b647).

## Historical deployed identity — builder-collected 2026-09-05 record (c5e6163)

These values were read from the host's release identity files and interpreter. They are
builder-collected operational evidence, not a signed or independently anchored attestation.

| Field | Value |
|---|---|
| Host | `docket.gudman.xyz` |
| `RELEASE-commit.txt` | `c5e6163eb05f54b406731c05a3fdc9fd4de020a2` |
| Wheel filename | `docket-0.1.0-py3-none-any.whl` |
| Wheel SHA-256 | `8997774d43de32825cbfe91fef6da8a53366983fcd7a0ea65f4f7f4fd29cb464` |
| Runtime-lock SHA-256 | `2b0fb7bc65a54cb8a648155108cbda3a920b40397f02b1f1fd0d8007cf14d33c` |
| Release-manifest SHA-256 | `9157bf43b326cc1704b364fb2cda01d7e7050d10d9650c4e2f2ac3aa6f604f7d` |
| Runtime Python | `3.12.3` |
| `.venv` target | `/opt/docket-venvs/c5e6163eb05f` |
| Database backup | `/var/backups/docket/agents-20260904T225814Z.sqlite3`; mode `0600`, owner `root:root` |
| Marketplace | Six services; four declared categories; nine v3 families; all six `paid_stock=false` |
| Non-payment timers | Nine enabled and active; v3-07 at `2026-09-05 11:50:00 UTC`, v3-08 at `2026-09-06 11:50:00 UTC` |
| Canary timer | disabled and inactive |

The runtime-lock digest is unchanged from the previous release, so this release moved no
dependency. GitHub Actions run `33927181234` passed all six jobs on the exact production
commit. At `2026-09-05T06:07Z`, `/api/status` was `degraded` only because an incomplete
refresh candidate remained after repeated filtered 8004scan page failures; the two failed
candidates each stopped at 400 of 473 expected agents, and a direct host probe of their next
page timed out. The last complete snapshot remained served, the database and archive RPC
were healthy, and the next normal retry was scheduled for `2026-09-05T07:41Z`. This is an
as-of outage note, not a continuing-status claim.

Production identifies `c5e6163eb05f54b406731c05a3fdc9fd4de020a2`. The source base before
this documentation update identified the same commit; the later documentation commit does
not change the deployed runtime. The approved run-18 payment evidence and the boundary that
public stock remains closed are recorded in
[`operational-evidence.md`](operational-evidence.md#collected-2026-08-30--approved-settlement-canary-and-current-state),
and this release is recorded in
[`operational-evidence.md`](operational-evidence.md#collected-2026-09-05--marketplace-release-of-c5e6163).

## Historical deployed identity — builder-collected 2026-09-02 record

These values were read from the host after the release then current. They are retained as a
historical builder-collected record and cover no later deployment.

| Field | Value |
|---|---|
| Host | `docket.gudman.xyz` |
| `RELEASE-commit.txt` | `4a632c01ebcfdccaed36e642cec2e74adbb69381` |
| Wheel filename | `docket-0.1.0-py3-none-any.whl` |
| Wheel SHA-256 | `923d410953e11bd98cec7dc9d26ef371ccd6e5c73bb8f11d3ce964c32b3769b6` |
| Runtime-lock SHA-256 | `2b0fb7bc65a54cb8a648155108cbda3a920b40397f02b1f1fd0d8007cf14d33c` |
| Runtime Python | `3.12.3` |
| `.venv` target | `/opt/docket-venvs/4a632c01ebcf` |
| Canary timer | disabled and inactive |

That release is recorded in
[`operational-evidence.md`](operational-evidence.md#collected-2026-09-02--release-of-4a632c0).

## Historical deployed identity — builder-collected 2026-08-16 record

Every value in this section is a historical as-of record that covers no later commit. The
builder collected the values from the host after the 12:20Z deploy and committed them to
`docs/operational-evidence.md`:

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
  locally, and public visibility alone does not independently timestamp commits or make the
  owner-controlled ref immutable.
- **What would close the gap:** an external timestamp or chain commitment over the stage-one
  protocol hash, recorded before inputs or runs. Not yet done.

The repository is **public** (verified 2026-08-28).

## Source roots

| Root | Contents | Shipped in wheel |
|---|---|---|
| `docket/` | Runtime package, API, services, evidence builders, packaged artifacts | Yes |
| `experiments/` | Read-only/simulation helpers and committed result JSON | Python package yes; result JSON stays at repository root except packaged evidence under `docket/` |
| `abis/` | Contract ABIs used by experiments/tests | No package-data rule |
| `tests/` | Source tests and installed-wheel smoke | No |
| `docs/` | Plans, audits, architecture, runbook, threat model, API/evidence docs | No |
| `data/` | Ignored runtime SQLite state plus committed registered v3 pool captures | No |

## Explicit Python packages

`pyproject.toml` declares:

```text
docket
docket.advantage
docket.advantage.v2
docket.advantage.v3
docket.advantage.v3.seats
docket.api
docket.agents
docket.agents.grid
docket.agents.pancake
docket.agents.venus
docket.agents.yield_router
docket.escrow
docket.execution
docket.hire
docket.identity
docket.jobs
docket.jobs.executors
docket.marketplace
docket.sessions
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
- V3 specifications, source snapshots, locked inputs, served report shell, and any JSONL
  ledgers, nested score sheets, or mappings present in the source tree.
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
| `docket/advantage/experiments/01-liquidity/live-audit.json` | `742ddd03abbbf9df8db5548bad98a7925b3c14eb57ccba48963bdf8cba3bb6c9` |
| `docket/advantage/experiments/02-trading.json` | `8735817bff88dc9b065f03fbdac7cefc5abaebbe28c94b16f9ebb4e9e90f4c17` |
| `docket/advantage/experiments/03-security.json` | `f4ad3c87b8cef5101dc1d1ed2e947b5012c7f77d0ff9d6d81cef1941b5c53f0c` |
| `docket/advantage/v2/corpus/liquidity/pools.json` | `f60b68ed4b7b4a04dec6f3772c9f8aab0955d0c1ad5d44397a16fddccfc015d5` |
| `docket/advantage/v2/corpus/security/payloads.json` | `11e9094f5a4a106d2f85be7a143c8c28ee6ee56c0521d1a0cda9672edab9f60a` |
| `docket/advantage/v2/corpus/series/bnbusdt-1h-2026-07.json` | `d642d970928d9ec45b228c047b4bc7fd99a62964515b68342c5eeb64c5003b72` |
| `docket/advantage/v2/specs/01-liquidity-arithmetic.json` | `72543e94358080b1daa9a349b99e48958e7fed2e0a0674d2ea0c11ae220cab50` |
| `docket/advantage/v2/specs/03-security-corpus.json` | `86c439c2f146db8dc2209fa006b0d3467ee8cb96d57711334c0ccda5852b5f5c` |
| `docket/advantage/v2/specs/05-security-corpus-postfix.json` | `cca312bcabbb9c2a79bbbea1333612c15a2f80536f5db0c0245c349692cac195` |
| `docket/advantage/v2/specs/04-grid-replay.json` | `2b22203c457edf86023c6574e8d2805fc819ff469bd3fc4b2c18068eb5adc84d` |
| `docket/advantage/v2/runs/01-liquidity-arithmetic.json` | `bcb4836197192cb275a4d520646ef2c4d345023dcc547cbdb2d7a5afe10f35a7` |
| `docket/advantage/v2/runs/03-security-corpus.json` | `b67f0d3c1b923065c505705fe3358d0e7dacb64e6c15da4d0d33f2896afa34f0` |
| `docket/advantage/v2/runs/05-security-corpus-postfix.json` | `456e1ee9cc5656097e7eb24dbf50fd234b5d31ade5e900edfd18f1bc71211a33` |
| `docket/advantage/v2/runs/04-grid-replay.json` | `7a81088a5b7189c5b260e0957e1221b2557711bc8f71f934515b0dbc82128af4` |
| `docket/advantage/v3/specs/v3-01-range-doctor.json` | `2146cbf9c7886f3d1059d496f0469d3fcff01aed1e18e5fb48813c7a4421826f` |
| `docket/advantage/v3/specs/v3-02-yield-router.json` | `43fcf0f446d38a8cf07951f0ca61c1f61d7cc61fc14f83619b6a00dfca7c31a0` |
| `docket/advantage/v3/specs/v3-03-warden-security.json` | `d18270a88d0bfcd4d2fae807824427d117e7a1d6440317afd5b8a519cd1e9771` |
| `docket/advantage/v3/specs/v3-04-warden-security.json` | `7c8b964f26bbdf120d7ac717c062cb27d92392c78a044babf715a94d7bd14b7c` |
| `docket/advantage/v3/specs/v3-05-range-doctor.json` | `23208479f4f96ee0e8ec878fb49bf08c6918849e2cce022e57fe971ae5f123fe` |
| `docket/advantage/v3/specs/v3-06-yield-router-assisted.json` | `2ac836e15989710aec91ce9c2ebeb8fac49e32962c595cebfdbf09e5aad766d5` |
| `docket/advantage/v3/specs/v3-07-range-doctor.json` | `7423d660bcaa7f05fd99d4b5bf049f5ffde7e8016a04e934b0d3105065b2fe44` |
| `docket/advantage/v3/specs/v3-08-yield-router.json` | `f439b7c606bfda2613d842e314499b8677cad2b45369cdee1dc11bc93ba7577d` |
| `docket/advantage/v3/specs/v3-09-health-guard.json` | `524bd4820f58469756e0d3fbedef7d26b61d571f2c6d8a71e43b6b91c95fa2d8` |
| `docket/advantage/v3/sources/health-v9-calibration-set.json` | `23845a548d2551383bba62f814b00bb317316c6e814f936e453d203374a9c457` |
| `docket/advantage/v3/sources/range-v5-calibration-set.json` | `df2e7247f712247462689b7718ee978e6bbb7596ebf05998754ec8bb540b77c6` |
| `docket/advantage/v3/sources/range-v5-enumerable-frame.json` | `ea41a6391e2d40f15c394224d9c7b0699b3eeca4968a2de9f75c43df32469761` |
| `docket/advantage/v3/sources/range-v5-evaluator-calibration.json` | `08e39929d39a9042cb24d18911257233ed3e77bc6951184554bb1f0d7ca27f55` |
| `docket/advantage/v3/sources/range-v5-pool-truth.json` | `da230d53de248dba9f9241e090a3a1a6b1b8cb6c5e6962db99ac00db5cce147f` |
| `docket/advantage/v3/sources/range-v7-calibration-set.json` | `c5bae93a3e93552fd2777e6fcc76b1610bcc45ad2dafb7165908213e8ff45287` |
| `docket/advantage/v3/sources/range-v7-enumerable-frame.json` | `29210a54f58c2b75ddb0f481d7ea86fe09bfa9f935665e52a2c140b43bf5a33d` |
| `docket/advantage/v3/sources/warden-calibration-set.json` | `63d2c6d750127e3ab874b02b87d1921a6685cf3ae1b79c3727ef7c05829a3fcf` |
| `docket/advantage/v3/sources/warden-heldout-cases.json` | `3ae8fb89f81ef9fb8147a8f6e2d8b921457c1ec9a31596b76f2055245ead12d4` |
| `docket/advantage/v3/sources/warden-reason-codes.html` | `918243ffe946df74b6307eadbb23398ba53c1bcea070cdb328877e3b65e31e63` |
| `docket/advantage/v3/sources/warden-v4-calibration-set.json` | `68850351a675ef6a6f0293d9108112318b42324477c6f87cbb2fe41841d5e55b` |
| `docket/advantage/v3/sources/warden-v4-heldout-cases.json` | `a06795b6c2eabbd0581be61cd26c5ed163eb406c5b958885e32c06834b658df7` |
| `docket/advantage/v3/sources/warden-v4-vendor-snapshot.json` | `8db24277dea2154e15f0b8e0f70941dfc62494f501b21fb838733e0b5a046bf7` |
| `docket/advantage/v3/sources/warden-vendor-snapshot.json` | `3afc28c59abb6a115ae75172b14a07b8050881f8f9b5c6a397f40df939790de7` |
| `docket/advantage/v3/sources/yield-v2-calibration-set.json` | `4194cd7f5ae7b5eb6535a8a228deaf238b80ee68630bf0a18ca8bb4bb0f2c5b6` |
| `docket/advantage/v3/sources/yield-v2-evaluator-calibration.json` | `de46911bed9c8f7fe993e39f4668fd86240f1edc77fa517e7c96cd854636e4e7` |
| `docket/advantage/v3/sources/yield-v6-assisted-calibration-set.json` | `a78ac78c79ef3b47905db0d2b365a82a2d31d24940b3867e87c21954ff59f08f` |
| `docket/advantage/v3/sources/yield-v8-calibration-set.json` | `434011a5d1e60accc718d56b1f2fd3146fa8e46335c5aa129a640b7f3353ac6c` |
| `docket/advantage/v3/provenance/warden-v3-03-pilot.json` | `8ed4c761e10c590da88c04764536d791ab5c3f2aa68d0945378c41f572cb99ef` |
| `docket/advantage/v3/provenance/warden-pilot-history.json` | `2221f0c31f594c8dcf90aeaafaf2de241b77c095cdb4730b6cabb248f8103419` |
| `docket/advantage/v3/provenance/range-v3-05-feasibility.json` | `6f878193b0b8fbf973c363f358ab5e932515a3f9770934406048d55d5b565874` |
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
