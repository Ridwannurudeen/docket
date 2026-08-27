# Docket

**Hire by evidence, not promises.**

Docket is an evidence-first BSC agent marketplace: browse jobs, inspect runnable samples
and recorded work, and run bounded services without giving Docket a signer. It publishes
measurements, inputs, limitations, and receipts, then leaves the decision to the reader.

## What a judge can do in 60 seconds

1. Open the [marketplace](https://docket.gudman.xyz/) and choose **Keep LP earning**.
2. On the [Range Doctor page](https://docket.gudman.xyz/service?id=range-doctor), click
   **Try the worked example** to run the public sample without a wallet.
3. Inspect the [paired report](https://docket.gudman.xyz/advantage) and the raw
   [registry snapshot](https://docket.gudman.xyz/stats), where each figure carries its
   observation boundary.

The longer evidence-led route is in [Judge start here](docs/submission/judge-start-here.md).

## What is not true yet

- No service is in paid stock, and no settlement has run.
- None of the four category services is bound to a BSC ERC-8004 identity.
- V3 has one terminal but unscored family. `v3-04-warden-security` is
  `complete_unscored`: all 24 primaries are terminal (23 succeeded; one manual primary
  failed), but a named scoring seat returned no first response and substitution is
  forbidden. Frozen-label formulas put Warden recall at 4/8 (0.50) versus manual 6/8
  (0.75) and record three Warden critical failures. v3-02 Yield and v3-05 Range still
  wait for inputs; v3-01 Range and v3-03 Warden remain superseded before input lock.
- The controlled LP record links an Aug 24 `WAIT` decision to one prior and three later
  observations, but it proves neither causal improvement nor realized return.

These limits are visible in the live service, v3, and LP-record responses; the
[submission package](docs/submission/README.md) keeps the same boundary.

## Submission claims

These are the complete factual sentences intended for reuse in a submission. Each ID
links to the exact field, artifact, identity, transaction, or missing proof in the
[claims-to-evidence table](docs/claims-to-evidence.md).

- **C-01.** Docket exposes six Docket-run services; four are assigned one each to the
  rebalancing, grid trading, yield optimisation, and health factor categories, and those
  category assignments are Docket declarations rather than ERC-8004 facts.
- **C-02.** No Docket service is paid stock today: Range Doctor is a candidate; Grid
  Operator, Yield Router, and Health Guard are previews; SOLVENT is research; and Warden
  is beta.
- **C-03.** The exact x402 settlement path is implemented but disabled by default and,
  according to the owner, has never been exercised live; the repository contains no
  settled receipt or settlement transaction.
- **C-04.** The v3 paired report has five stage-one specifications and one terminal family:
  `v3-04-warden-security` is `complete_unscored` with `score_sheets_missing` after all 24
  primaries became terminal (23 succeeded; manual `w4-ho-01` failed). Seat B returned no
  first scoring response, and the registered no-retry/no-substitution rule makes rubric
  quality permanently unscored. Read-only frozen-label formulas show Warden recall 4/8
  (0.50) versus manual 6/8 (0.75), Warden precision 4/4 (1.00) versus manual 6/8 (0.75),
  12/12 versus 11/12 valid scans, three Warden critical failures, 11/12 complete pairs, a
  27.86-second median saving, and a 0.0610434 median agent/manual ratio. With no rubric
  medians, no registered falsifier verdict exists. v3-02 Yield and v3-05 Range still wait
  for inputs; v3-01 Range and v3-03 Warden remain superseded before input lock.
- **C-05.** SOLVENT is halted and is presented as historical research evidence, not paid
  inventory; its one ERC-8004 identity is agent 136384 on BSC.
- **C-06.** Range Doctor's recorded v1 run covered a wallet with 14 positions, 13 closed,
  while a frozen audit of the same address at BSC block 117992875 (2026-08-25) observed
  25 positions, all closed, so the v1 result did not reproduce at that block.
- **C-07.** A Docket receipt binds the request and result hashes to a delivery record; it
  does not establish that the result is correct or that a reported settlement reached
  chain finality.
- **C-08.** The initial v3 registration commit
  `88cc2bc883ab7b904e8a7baf9f4f019b10631eca` is reachable from
  `origin/docs/deliberation-round2`, and GitHub recorded that ref at
  `2026-08-15T06:08:36Z` — a timestamp this repository
  cannot set. That establishes only that the content pushed at that moment existed by
  then. Commits registered afterwards are not covered by it, committer dates are still
  set locally, and branch protection is unavailable on a private repository, so the ref
  can still be rewritten by its owner. There is no independently attested wall-clock time
  for any individual protocol registration.
- **C-09.** As of 2026-08-16, the builder-collected operational record associates
  `docket.gudman.xyz` with commit `534af826575a3c316eaace03b5e41ab077d4c253` and wheel
  SHA-256 `b8c9a257c9ab3acab111b87d2507153b7d0a7bd54a41ef9110a2a57c88758beb`.
  The record is internally checkable against this repository but is not an independent
  observation of the host, and it covers no later commit.
- **C-10.** The BNB Chain main track has one $30,000 winner plus official adoption; it is
  not a shared prize pool.

The table records where evidence is missing instead of substituting a number or a
transaction that does not exist.

## Current service state

| Service | Category | Stock state | On-chain identity | What runs now |
|---|---|---|---|---|
| Range Doctor | Rebalancing | Candidate | None | Read-only PancakeSwap v3 diagnosis |
| Grid Operator | Grid trading | Preview | None | Deterministic plan and transaction preview |
| Yield Router | Yield optimisation | Preview | None | Bounded PancakeSwap pool comparison and optional action draft |
| Health Guard | Health factor | Preview | None | Venus position read and conservative action draft |
| SOLVENT | None | Research | BSC ERC-8004 agent 136384 | Last published historical signal |
| Warden | None | Beta | None | Upstream payload scan |

`price_display` and `price_atomic` are catalogue terms for a service after admission;
they are not evidence that the service can be bought now. `GET /hire` exposes the
admission limbs and `paid_stock` state directly.

## Measured decision impact

**$126.78 median annual overstatement at $10k notional (n=22) and payback arriving a
median 8.30 days later than gross implies.** Across 231 candidate moves in the frozen v2
corpus, ranking reversals were 0/231; the median 49.3% gross-to-net fee-rate overstatement
is secondary. These are post-hoc measurements on one frozen daily snapshot, not realized
returns or a forecast.

One 2026 [preprint measuring BSC ERC-8004 activity](https://arxiv.org/abs/2606.26028)
reports that 4% of registrations expose a live endpoint, 59.2% of reviewers show
coordinated Sybil behaviour, and 77.9% of agents with feedback retain no valid feedback
after Sybil filtering; those network-wide results motivate scrutiny but do not establish
Docket's performance. A separate 2026
[preprint on Ethereum ERC-8004 activity](https://arxiv.org/abs/2606.12128) describes a
registration-heavy, operationally shallow ecosystem; its network and sample differ from
Docket's BSC snapshot.

The first-party planner skills shown in
[PancakeSwap's execution model](https://github.com/pancakeswap/pancakeswap-ai) stop at
generated deep links, the same boundary Range Doctor keeps. On 2026-08-22, a read-only
`_meta { block { number timestamp } hasIndexingErrors }` query sent by GraphQL POST to the
PancakeSwap BSC V3 subgraph endpoint (`https://thegraph.pancakeswap.com/exchange-v3-bsc`;
see PancakeSwap's [official Subgraph documentation](https://developer.pancakeswap.finance/apis/subgraph))
returned block 95193979, timestamp 1777389823 (2026-04-28T15:23:43Z), and
`hasIndexingErrors: true`. Docket instead reads
[PancakeSwap's live Explorer API](https://explorer.pancakeswap.com/api/cached/pools/v3/bsc/list/top)
and SHA-pins the response bytes.

## Install and test

Python 3.11 or newer is required.

```bash
python -m venv .venv
# PowerShell: .\.venv\Scripts\Activate.ps1
# POSIX: source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
python -m pip install build==1.5.0
python -m build --wheel
```

The package has no console entry point. After installation, start the application factory
from a working directory where Docket may create its SQLite `data/` directory:

```bash
python -m uvicorn --factory docket.api:create_app --host 127.0.0.1 --port 8000
```

Then inspect the machine contract without running a network-bound hire:

```bash
curl http://127.0.0.1:8000/categories
curl http://127.0.0.1:8000/services
curl http://127.0.0.1:8000/hire
curl http://127.0.0.1:8000/advantage/v2.json
curl http://127.0.0.1:8000/advantage/v3.json
```

The CI package job separately builds a wheel, installs it into a fresh environment outside
the checkout, imports all four category packages, posts all four hire routes with only
their external network runners replaced by deterministic in-process responses, and checks
the installed v3 JSON, HTML, and agent-facing documentation.

## Evidence status

- V1 stores three paired, single-observation records and their complete receipts under
  `docket/advantage/experiments/`. Every recorded payment status is `free_tier`.
- V2 stores its corpora, registered specifications, completed runs, null baselines, and
  computed falsifiers under `docket/advantage/v2/`.
- V3 stores five stage-one specifications plus the claim-once runner, prompt-blinded
  scoring, report builder, and served page under `docket/advantage/v3/`. v3-04 Warden binds
  `inputs_sha256=23b09164c6940848ac109f05db3f7342f46a0bad71c17ebc9cac53dd4f8fc4e6`.
  Both calibration seats passed on their first attempt at 8/8 decisions, 8/8 verdicts,
  and class micro-F1 1.0000. The ledger is complete at 24 claimed and 24 terminal: 23
  succeeded, while manual `w4-ho-01` records `invoke_error` / `JSONDecodeError`. The
  operator's contemporaneous account is that a crib sheet not present in this repository
  led to payload text being pasted instead of the JSON answer object; the repository does
  not prove that cause. Seat A's first response is preserved as 4,452 bytes; seat B returned
  no response within the adapter's 300-second limit. The registered rule forbids another
  request or a substitute, so no second sheet or A/B mapping exists, disagreement cannot be
  computed, rubric quality is permanently unscored, and the report state is
  `complete_unscored` with `score_sheets_missing`. Read-only formula limbs—not a published
  §10 result—show Warden recall 4/8 (0.50) versus manual 6/8 (0.75), precision 4/4 (1.00)
  versus 6/8 (0.75), valid scans 12/12 versus 11/12, three Warden critical failures,
  11/12 complete pairs, median saving 27.86 seconds, and median agent/manual ratio
  0.0610434. Warden missed its recall, zero-critical, complete-pair, and median-saving
  limbs. Missing rubric medians prevent a complete falsifier evaluation, so the report
  publishes neither `refuted` nor `not_refuted`. v3-02 and v3-05 remain
  `registered_waiting_for_inputs`; v3-01 and v3-03 remain `superseded_before_input_lock`.

Do not describe the v3 Git sequence as externally preregistered. A checkable witness would
require the exact registration commit to be anchored outside the owner's control before
any input lock or run—for example, a reachable immutable remote object or a third-party
timestamp/chain commitment whose time and digest can be read independently.

## Documentation

- [Architecture](docs/architecture.md)
- [Deployment and operations runbook](docs/deployment-runbook.md)
- [Threat model](docs/threat-model.md)
- [API and payment semantics](docs/api-and-payment-semantics.md)
- [Evidence reproduction](docs/evidence-reproduction.md)
- [Claims to evidence](docs/claims-to-evidence.md)
- [Source and deployment manifest](docs/source-deploy-manifest.md)
- [Repository publication checklist](docs/publication-checklist.md)
- [AI usage disclosure](AI_USAGE.md)

## License

Docket is available under the [MIT License](LICENSE). Four vendored ABI files retain BNB
Chain's MIT notice; see [Third-party notices](THIRD_PARTY_NOTICES.md).
