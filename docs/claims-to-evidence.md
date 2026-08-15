# Claims to evidence

This table is the complete allowlist of factual submission sentences in the root README.
Reuse the sentence and its boundary together. A missing proof remains `missing`; it is not a
request to infer a number, identity, endorsement, or transaction.

| ID | Exact submission sentence | API field, artifact hash, identity, or transaction | Boundary |
|---|---|---|---|
| C-01 | Docket exposes six Docket-run services; four are assigned one each to the rebalancing, grid trading, yield optimisation, and health factor categories, and those category assignments are Docket declarations rather than ERC-8004 facts. | `GET /services.total=6`; `GET /categories.categories[].{category,service_count,services_path}` with four `service_count=1`; `/categories.declaration`; `/services.services[].{service_id,category,hire_path}`. | Four services, not four registered agents; the four category `agent_id` values are null. |
| C-02 | No Docket service is paid stock today: Range Doctor is a candidate; Grid Operator, Yield Router, and Health Guard are previews; SOLVENT is research; and Warden is beta. | `GET /hire.services[].{id,paid_stock,stock_status,admission}` and `GET /services.services[].{service_id,paid_stock,stock_status}`; all six `paid_stock=false`. | Status is current source state, not a promise that a later deployment is unchanged. |
| C-03 | The exact x402 settlement path is implemented but disabled by default and, according to the owner, has never been exercised live; the repository contains no settled receipt or settlement transaction. | `docket/hire/x402.py`; `docket/api/routes.py` owner gate; all three v1 receipt `payment.status=free_tier`; **settled receipt: missing**; **settlement transaction: missing**. | Source proves the disabled default and missing repository evidence. “Never exercised live” is explicitly owner operational state, not a globally provable negative. |
| C-04 | The v3 paired report has three stage-one specifications, but no input is locked and no arm has run. | `GET /advantage/v3.json`: `summary.n_families=3`, `summary.states.registered_waiting_for_inputs=3`; Range hashes `0xcfaf6d…68bd6` / `0x2d3a61…0d282`; Yield `0x2d567e…54ace` / `0x9455cc…baa1e`; Warden `0x919b37…fb4bf` / `0x27ce69…db01b`; every `inputs_sha256=""`; input/run artifacts **missing**. | The served state reports registration and missing inputs, not the outcome of a future run. |
| C-05 | SOLVENT is halted and is presented as historical research evidence, not paid inventory; its one ERC-8004 identity is agent 136384 on BSC. | `GET /hire` record `id=solvent-signal`, `paid_stock=false`, `stock_status=research`; identity `56:0x8004a169fb4a3325136eb29fa0ceb6d2e539a432:136384`; v1 task-02 file SHA-256 `8735817bff88dc9b065f03fbdac7cefc5abaebbe28c94b16f9ebb4e9e90f4c17`. | Halted is owner/recorded operational state. The identity does not endorse the signal. |
| C-06 | Range Doctor's recorded v1 run covered a wallet with 14 positions, 13 closed, while the repository's latest live audit recorded 21 positions and all 21 closed, so that historical result is not reproducible against the same address now. | V1 task-01 file SHA-256 `c048e5ede594f4bb7055dcba871acf9c1c3a22bfd1100f5504377fa4f8394116`; receipt input/output hashes `0x916b75…b852` / `0xf95c55…a7ce`; wallet `0x451871A1753903FB8fdd64a6B838E95aB8D5B80f`; latest live-audit file SHA-256 `5397ba7961b4ae0a511a75db80c13d8a0543f02a2ae4975550cf0dfb88d95955`. | The 21-closed observation was not rerun for this documentation build and is not a frozen current-chain artifact. It invalidates live-address reproduction, not the committed historical bytes. |
| C-07 | A Docket receipt binds the request and result hashes to a delivery record; it does not establish that the result is correct or that a reported settlement reached chain finality. | Receipt fields `{service,input_hash,output_hash,delivered_at,payment}`; canonical recipe in `docket/hire/receipts.py`; v1 task-01 exact input/output hashes above. | Cryptographic binding is not evaluation. A `settled` block would be a facilitator response, not an independent chain receipt. |
| C-08 | The current v3 registration sequence is only a self-controlled local Git witness: it is not reachable from the configured remote refs, can be rewritten by the repository owner, and has no independently attested wall-clock time. | Registration commit `88cc2bc883ab7b904e8a7baf9f4f019b10631eca`; `git branch -a --contains`; backdating-audit file SHA-256 `53aeee2e0af8091741917b6bc3e6de96c92d8d3d36c19ace044e0e2778ac3973`; every spec's `registration_provenance`. | Local refs cannot prove that no external copy exists. They prove only what this checkout records. |
| C-09 | No source-to-deployment parity evidence exists for this build, so this package makes no claim that a public deployment runs this revision. | **Release commit: missing**; **deployed wheel SHA-256: missing**; **deployment record: missing**; see `docs/source-deploy-manifest.md`. | A local build or health response alone would not establish source/live parity. |

## Evidence classes

- **API field:** inspectable through the current application contract; still depends on what
  source/deployment is running.
- **Artifact hash:** identity of exact committed bytes, not endorsement of their content.
- **Identity:** chain/contract/token tuple or transaction locator; not evidence of service
  quality.
- **Transaction:** evidence of a chain event at a block; interpretation stays bounded to the
  event and data it contains.
- **Missing:** the repo cannot support the claim. Do not replace it with prose.

## Claims deliberately absent

The public package does not say Docket is independently verified, trusted, recommended,
endorsed, production-settled, deployed from this revision, profitable, loss-avoiding, or
supported by a completed v3 report. It does not quote Grid, Yield, or Health performance
because those services have no recorded paired metrics. It does not turn SOLVENT's halted
history into inventory or treat Range's stale evidence address as a reproducible demo.
