# Docket

Docket is an evidence-first interface for inspecting ERC-8004 agent observations and
running bounded services on BNB Smart Chain. It publishes measurements, inputs,
limitations, and receipts; it does not publish a trust score or choose an agent for the
reader.

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
- **C-04.** The v3 paired report has three stage-one specifications, but no input is
  locked and no arm has run.
- **C-05.** SOLVENT is halted and is presented as historical research evidence, not paid
  inventory; its one ERC-8004 identity is agent 136384 on BSC.
- **C-06.** Range Doctor's recorded v1 run covered a wallet with 14 positions, 13 closed,
  while the repository's latest live audit recorded 21 positions and all 21 closed, so
  that historical result is not reproducible against the same address now.
- **C-07.** A Docket receipt binds the request and result hashes to a delivery record; it
  does not establish that the result is correct or that a reported settlement reached
  chain finality.
- **C-08.** The current v3 registration sequence is only a self-controlled local Git
  witness: it is not reachable from the configured remote refs, can be rewritten by the
  repository owner, and has no independently attested wall-clock time.
- **C-09.** No source-to-deployment parity evidence exists for this build, so this package
  makes no claim that a public deployment runs this revision.

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

## Install and test

Python 3.11 or newer is required.

```bash
python -m venv .venv
# PowerShell: .\.venv\Scripts\Activate.ps1
# POSIX: source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
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
```

The CI package job separately builds a wheel, installs it into a fresh environment outside
the checkout, imports all four category packages, and posts all four hire routes with only
their external network runners replaced by deterministic in-process responses.

## Evidence status

- V1 stores three paired, single-observation records and their complete receipts under
  `docket/advantage/experiments/`. Every recorded payment status is `free_tier`.
- V2 stores its corpora, registered specifications, completed runs, null baselines, and
  computed falsifiers under `docket/advantage/v2/`.
- V3 stores only the three stage-one specifications under
  `docket/advantage/v3/specs/`. There is no `inputs/` or `runs/` directory, every
  `inputs_sha256` is empty, and v3 is not served by an API route.

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
- [AI usage disclosure](AI_USAGE.md)

## License

Docket is available under the [MIT License](LICENSE).
