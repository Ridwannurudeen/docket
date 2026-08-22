# Codex ruling on the ChatGPT Pro audit (2026-08-22)

_Codex gpt-5.6-sol @ xhigh, 181,029 tokens, full-access sandbox with before/after tree hash (unchanged). Input: CHATGPT-PRO.md vs JOINT-AUDIT-2026-08-22.md._

## 1. Genuine additions worth adopting

- **Prize/rules correction — prose.** Change the joint audit’s “BNB top-3 / $30k” label to “BNB shortlist / single $30k winner.” Also describe repository publication as a credibility/reproducibility gate, not an explicit eligibility rule. Keep the public-flip task because the governing plan independently requires it. [ChatGPT Pro:21](docs/deliberation/2026-08-22-seats/CHATGPT-PRO.md:21>) [ChatGPT Pro:41](docs/deliberation/2026-08-22-seats/CHATGPT-PRO.md:41>) [Joint:47](docs/deliberation/JOINT-AUDIT-2026-08-22.md:47>) [Joint:306](docs/deliberation/JOINT-AUDIT-2026-08-22.md:306>)

- **Sharper evidence-first positioning — prose.** Adopt “Hire by evidence, not promises” and one carefully caveated preprint sentence using the stipulated corrected figure, **77.9%, not 72.3%**. This strengthens Docket’s existing evidence-without-trust-score thesis; it does not justify a ranking system. Touch [README.md:3](README.md:3>) and homepage copy at [index.html:48](docket/api/web/index.html:48>). ChatGPT’s source paragraph is at [CHATGPT-PRO.md:103](docs/deliberation/2026-08-22-seats/CHATGPT-PRO.md:103>).

- **Manifest–Verifier–Receipt as adoption narrative only — prose.** Use that trio to satisfy the joint audit’s requested “how a third party would list” explanation. Add it to [architecture.md:37](docs/architecture.md:37>); do not build a new manifest platform because service schemas and hash-bound receipts already exist at [architecture.md:44](docs/architecture.md:44>). [CHATGPT-PRO.md:587](docs/deliberation/2026-08-22-seats/CHATGPT-PRO.md:587>)

- **Explicit evidence-modality label — code.** During the already-scheduled vocabulary cleanup, add a small closed field such as `live_read`, `preview`, `historical`, `paired_benchmark`, or `replay` to the service/API/card models. Today `ServiceRecord` exposes activation, metrics and stock state but no structured modality. [models.py:216](docket/marketplace/models.py:216>) [api/models.py:178](docket/api/models.py:178>) [CHATGPT-PRO.md:230](docs/deliberation/2026-08-22-seats/CHATGPT-PRO.md:230>)

## 2. Conflicts and rulings

- **Repository knowledge:** ChatGPT explicitly had none; its architectural and implementation statements are hypotheses, not findings. Reject the Next.js/PostgreSQL/SDK rewrite: Docket is an existing FastAPI/Python/SQLite system. [CHATGPT-PRO.md:29](docs/deliberation/2026-08-22-seats/CHATGPT-PRO.md:29>) [pyproject.toml:9](pyproject.toml:9>) [architecture.md:96](docs/architecture.md:96>)

- **Verified badges, composite ranking, “Why Docket ranked…” and default Recommend:** reject. `verified`, `recommended`, `rank`, `score`, and `rating` are deliberately banned and contract-tested. [CHATGPT-PRO.md:124](docs/deliberation/2026-08-22-seats/CHATGPT-PRO.md:124>) [api/models.py:14](docket/api/models.py:14>) [test_api_contract.py:43](tests/test_api_contract.py:43>)

- **RangePilot execution, four live actors, equal-depth P0, builder onboarding:** reject. Range Doctor’s fund-safety advantage is structural read-only operation; broad parity, Grid execution and onboarding are explicitly cut. [doctor.py:1](docket/agents/pancake/doctor.py:1>) [Win spec:118](docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md:118>) [CHATGPT-PRO.md:967](docs/deliberation/2026-08-22-seats/CHATGPT-PRO.md:967>)

- **Infinity limit-order hook:** real, but defer. Current Grid is explicitly a V2 preview with no limit orders; building a new Infinity execution service violates the cut. [registry.py:151](docket/marketplace/registry.py:151>) [Joint:314](docs/deliberation/JOINT-AUDIT-2026-08-22.md:314>)

- **ERC-8183 as the judge-facing hire:** reject. Mainnet has a fixed seven-day dispute window and no early acceptance; keep it separate and use x402 for the immediate paid Range hire. [routes.py:969](docket/api/routes.py:969>) [architecture.md:53](docs/architecture.md:53>)

- **Its calendar and three suggested experiments:** reject. They replace preregistered Range/Yield/Warden evidence with new Grid/Liquidation work and ignore the actual settlement, capture, archive, owner-decision and deployment exits. [Win spec:19](docs/deliberation/CODEX-WIN-SPEC-2026-08-14.md:19>) [Joint:298](docs/deliberation/JOINT-AUDIT-2026-08-22.md:298>)

## 3. Net ruling

No verdict, date, or priority changes; only [Joint:47](docs/deliberation/JOINT-AUDIT-2026-08-22.md:47>) should be relabelled from “BNB top-3 / $30k” to “BNB shortlist / single $30k winner.”

## 4. What would hurt

The harmful instructions are the stack rewrite, ranking/badges, four-agent execution rebuild, Infinity Grid detour, builder platform, replacing preregistered experiments, and using seven-day ERC-8183 settlement for TermiX. Its proposed submission language would also overclaim capabilities while paid stock and v3 evidence remain absent. [README.md:17](README.md:17>) [README.md:23](README.md:23>)
