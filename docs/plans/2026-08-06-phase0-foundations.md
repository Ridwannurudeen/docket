# Docket Phase 0 — Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** De-risk the two facts the whole build depends on — (E1) whether ERC-8183 supports marketplace-evaluator instant settlement, and (SOLVENT) whether agent #136384 can be made legible to 8004scan — plus the repo scaffold everything later lands in.

**Architecture:** Three independent workstreams: a Python experiment script against BSC testnet 97 (raw web3 + vendored ABI, no SDK); a static registration JSON + nginx content-negotiation change in the existing `solvent` repo; and the `docket` Python scaffold. No marketplace code yet — Phase 1 plans are written after E1's result exists.

**Tech Stack:** Python ≥3.11, `web3==7.16.0`, `eth-account==0.13.7`, `pytest`; nginx (existing VPS vhost); `gh` CLI.

## Global Constraints

- Pins are exact and non-negotiable: `web3==7.16.0`, `eth-account==0.13.7`, `httpx==0.28.1` (matches warden/solvent house pins). solvent keeps `bnbagent==0.3.6` — do not upgrade it in any task.
- Testnet only for E1: chain id **97**. Contracts: commerce `0xa206c0517B6371C6638CD9e4a42Cc9f02A33B0DE`, $U `0xc70B8741B8B07A6d61E54fd4B20f22Fa648E5565` (18 decimals), $U faucet `0x86e9197CC0F76E4e4aaa7082180945196bBAb5D3`. RPC `https://bsc-testnet-rpc.publicnode.com`.
- Private keys live in env vars only (`E1_CLIENT_KEY`, `E1_EVALUATOR_KEY`); never in files, args, or output. `.env` is gitignored.
- No Claude/Anthropic attribution anywhere; no Co-Authored-By tags.
- VPS actions (deploy the JSON + nginx reload) are **user-approval-gated** and ship changed files individually — never a directory copy. Count `nginx -t` warnings against the known baseline of 22 before reload.
- Evidence integrity: E1's result file records what actually happened, including failure and revert reasons verbatim.
- solvent repo conventions: Python ≥3.12, tests under `tests/`, run `python -m pytest -q` from repo root.

---

### Task 1: Docket repo scaffold + vendored ERC-8183 ABI

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `abis/AgenticCommerce.json`, `abis/ERC20.json`, `tests/test_abis.py`
- (Repo root: `.`)

**Interfaces:**
- Consumes: nothing.
- Produces: `abis/AgenticCommerce.json` + `abis/ERC20.json` used by Task 2's script via `json.load(open("abis/AgenticCommerce.json"))`; a working `python -m pytest -q` gate.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "docket"
version = "0.1.0"
description = "Docket — trust-first agent marketplace for BSC (Build the Era)"
requires-python = ">=3.11"
dependencies = [
    "web3==7.16.0",
    "eth-account==0.13.7",
    "httpx==0.28.1",
]

[project.optional-dependencies]
dev = ["pytest==9.0.3"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write `.gitignore`**

```gitignore
__pycache__/
*.egg-info/
.venv/
.env
*.key
node_modules/
```

- [ ] **Step 3: Vendor the ABIs from the SDK repo (shallow clone, copy two files, delete clone)**

```bash
cd "."
git clone --depth 1 https://github.com/bnb-chain/bnbagent-sdk /tmp/bnbagent-sdk-abi
cp /tmp/bnbagent-sdk-abi/abis/AgenticCommerce.json abis/AgenticCommerce.json
cp /tmp/bnbagent-sdk-abi/abis/ERC20.json abis/ERC20.json
rm -rf /tmp/bnbagent-sdk-abi
```

If `abis/` is not at the clone root, find it: `find /tmp/bnbagent-sdk-abi -name "AgenticCommerce.json"` (the repo restructured on 2026-08-06; the shared root `abis/` is post-restructure). Record the source commit hash in the commit message.

- [ ] **Step 4: Write the failing test `tests/test_abis.py`**

```python
import json
from pathlib import Path

ABI_DIR = Path(__file__).resolve().parents[1] / "abis"


def _fn_names(abi: list) -> set[str]:
    return {e["name"] for e in abi if e.get("type") == "function"}


def test_commerce_abi_has_e1_functions():
    abi = json.loads((ABI_DIR / "AgenticCommerce.json").read_text())
    if isinstance(abi, dict):  # some repos wrap as {"abi": [...]}
        abi = abi["abi"]
    names = _fn_names(abi)
    for required in {"createJob", "setBudget", "fund", "submit", "complete", "jobs", "jobCounter", "claimRefund"}:
        assert required in names, f"missing {required}"


def test_erc20_abi_has_approve_and_balance():
    abi = json.loads((ABI_DIR / "ERC20.json").read_text())
    if isinstance(abi, dict):
        abi = abi["abi"]
    names = _fn_names(abi)
    assert {"approve", "balanceOf"} <= names
```

- [ ] **Step 5: Install and run the test**

```bash
cd "."
python -m pip install -e ".[dev]"
python -m pytest -q
```
Expected: PASS (2 passed). If `complete` is missing from the ABI, STOP — Task 2's premise is wrong; report before proceeding.

- [ ] **Step 6: Add CI — `.github/workflows/ci.yml`**

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install -e ".[dev]"
      - run: python -m pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore abis/AgenticCommerce.json abis/ERC20.json tests/test_abis.py .github/workflows/ci.yml
git commit -m "build: scaffold docket + vendor ERC-8183 ABIs (bnbagent-sdk @ <commit>) + CI"
```

After the next push, verify the workflow ran green: `gh run list --repo Ridwannurudeen/docket --limit 1`.

---

### Task 2: E1 — marketplace-evaluator instant-settlement experiment (testnet 97)

**Files:**
- Create: `experiments/e1_instant_settlement.py`, `tests/test_e1_helpers.py`
- Create (output, committed): `experiments/e1-result.json`

**Interfaces:**
- Consumes: `abis/AgenticCommerce.json`, `abis/ERC20.json` from Task 1.
- Produces: `experiments/e1-result.json` with shape `{"worked": bool, "job_id": int, "final_status": str, "provider_u_delta_wei": str, "txs": {step: hash}, "revert": str|null, "notes": str}` — Phase 1's hire-rail plan branches on `worked`.

**Question E1 answers:** the deployed kernel's `createJob` accepts an arbitrary `evaluator`; `complete(jobId, …)` is documented evaluator-only. If an EOA evaluator can `complete()` a job that never touched the router, Docket controls settlement timing (accept-is-settlement). All 56k mainnet jobs used the router, so this path is unexercised — that is *why* it needs the experiment.

- [ ] **Step 1: Read the exact input types for `createJob`, `setBudget`, `fund`, `submit`, `complete` from `abis/AgenticCommerce.json`**

Do not trust this plan's assumed shapes — read the ABI entries and note each function's inputs (names, types, order) and the `jobs(uint256)` output tuple order. The status enum order is `["OPEN","FUNDED","SUBMITTED","COMPLETED","REJECTED","EXPIRED"]`. Adjust Step 3's calls to the ABI's actual signatures.

- [ ] **Step 2: Write the failing helper test `tests/test_e1_helpers.py`**

```python
from experiments.e1_instant_settlement import canonical_manifest_hash, STATUS


def test_canonical_manifest_hash_is_stable_and_key_ordered():
    a = canonical_manifest_hash({"b": 1, "a": {"y": 2, "x": 1}})
    b = canonical_manifest_hash({"a": {"x": 1, "y": 2}, "b": 1})
    assert a == b
    assert a.startswith("0x") and len(a) == 66


def test_status_enum_order():
    assert STATUS[0] == "OPEN" and STATUS[3] == "COMPLETED"
```

Run: `python -m pytest tests/test_e1_helpers.py -q` → Expected: FAIL (module not found).

- [ ] **Step 3: Write `experiments/e1_instant_settlement.py`**

```python
"""E1: can a non-router evaluator settle an ERC-8183 job instantly? (BSC testnet 97)

Env: E1_CLIENT_KEY (funded with tBNB; acts as client AND provider),
     E1_EVALUATOR_KEY (the 'Docket marketplace' evaluator; script funds it from client).
Run: python -m experiments.e1_instant_settlement
"""

import json
import os
import time
from pathlib import Path

from eth_account import Account
from web3 import Web3

RPC = "https://bsc-testnet-rpc.publicnode.com"
CHAIN_ID = 97
COMMERCE = Web3.to_checksum_address("0xa206c0517B6371C6638CD9e4a42Cc9f02A33B0DE")
U_TOKEN = Web3.to_checksum_address("0xc70B8741B8B07A6d61E54fd4B20f22Fa648E5565")
U_FAUCET = Web3.to_checksum_address("0x86e9197CC0F76E4e4aaa7082180945196bBAb5D3")
ZERO = "0x0000000000000000000000000000000000000000"
STATUS = ["OPEN", "FUNDED", "SUBMITTED", "COMPLETED", "REJECTED", "EXPIRED"]
BUDGET = 10**16  # 0.01 $U
ROOT = Path(__file__).resolve().parents[1]


def canonical_manifest_hash(manifest: dict) -> str:
    blob = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return Web3.keccak(blob).to_0x_hex()


def _load_abi(name: str) -> list:
    abi = json.loads((ROOT / "abis" / name).read_text())
    return abi["abi"] if isinstance(abi, dict) else abi


def _send(w3, acct, tx_dict, label, txs):
    tx_dict.setdefault("nonce", w3.eth.get_transaction_count(acct.address))
    tx_dict.setdefault("chainId", CHAIN_ID)
    tx_dict.setdefault("gasPrice", w3.eth.gas_price)
    tx_dict.setdefault("gas", int(w3.eth.estimate_gas({**tx_dict, "from": acct.address}) * 1.3))
    signed = acct.sign_transaction(tx_dict)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(h, timeout=120)
    txs[label] = h.to_0x_hex()
    if receipt.status != 1:
        raise RuntimeError(f"{label} reverted: {h.to_0x_hex()}")
    return receipt


def main() -> int:
    w3 = Web3(Web3.HTTPProvider(RPC))
    client = Account.from_key(os.environ["E1_CLIENT_KEY"])
    evaluator = Account.from_key(os.environ["E1_EVALUATOR_KEY"])
    commerce = w3.eth.contract(address=COMMERCE, abi=_load_abi("AgenticCommerce.json"))
    u = w3.eth.contract(address=U_TOKEN, abi=_load_abi("ERC20.json"))
    txs: dict[str, str] = {}
    result = {"worked": False, "job_id": None, "final_status": None,
              "provider_u_delta_wei": None, "txs": txs, "revert": None, "notes": ""}
    try:
        # 0) evaluator gas: top up from client if evaluator has < 0.002 tBNB
        if w3.eth.get_balance(evaluator.address) < w3.to_wei("0.002", "ether"):
            _send(w3, client, {"to": evaluator.address,
                               "value": w3.to_wei("0.005", "ether")}, "fund_evaluator_gas", txs)
        # 1) $U: faucet gives 10 $U per call
        if u.functions.balanceOf(client.address).call() < BUDGET:
            faucet = w3.eth.contract(address=U_FAUCET, abi=[{
                "name": "requestTokens", "type": "function",
                "stateMutability": "nonpayable", "inputs": [], "outputs": []}])
            _send(w3, client, faucet.functions.requestTokens().build_transaction(
                {"from": client.address}), "u_faucet", txs)
        u_before = u.functions.balanceOf(client.address).call()
        # 2) createJob with evaluator = Docket EOA, hook = 0, NO registerJob
        expired_at = int(time.time()) + 3600
        rcpt = _send(w3, client, commerce.functions.createJob(
            client.address, evaluator.address, expired_at, "E1 instant-settlement probe", ZERO
        ).build_transaction({"from": client.address}), "create_job", txs)
        job_id = commerce.functions.jobCounter().call()
        result["job_id"] = job_id
        # 3) budget + approve + fund
        _send(w3, client, commerce.functions.setBudget(job_id, BUDGET, b"").build_transaction(
            {"from": client.address}), "set_budget", txs)
        _send(w3, client, u.functions.approve(COMMERCE, BUDGET).build_transaction(
            {"from": client.address}), "approve", txs)
        _send(w3, client, commerce.functions.fund(job_id, BUDGET, b"").build_transaction(
            {"from": client.address}), "fund", txs)
        # 4) provider (== client) submits a deliverable
        manifest = {"service": "e1-probe", "content": "hello", "ts": expired_at}
        opt = json.dumps({"deliverable_url": "https://docket.gudman.xyz/e1"},
                         sort_keys=True, separators=(",", ":")).encode()
        _send(w3, client, commerce.functions.submit(
            job_id, Web3.to_bytes(hexstr=canonical_manifest_hash(manifest)), opt
        ).build_transaction({"from": client.address}), "submit", txs)
        # 5) THE TEST: evaluator EOA calls complete() immediately (no dispute window)
        _send(w3, evaluator, commerce.functions.complete(job_id, "accepted", b"").build_transaction(
            {"from": evaluator.address}), "complete", txs)
        status = STATUS[commerce.functions.jobs(job_id).call()[7]]
        result["final_status"] = status
        result["provider_u_delta_wei"] = str(u.functions.balanceOf(client.address).call() - u_before)
        result["worked"] = status == "COMPLETED"
        result["notes"] = "complete() from a plain EOA evaluator; job never registered with the router"
    except Exception as exc:  # record the failure verbatim — that IS the experiment result
        result["revert"] = repr(exc)
    (ROOT / "experiments" / "e1-result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["worked"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

Adjust `complete(...)`'s arguments and the `jobs()` tuple index for `status` to the actual ABI read in Step 1 (the assumed shapes are `complete(uint256,string,bytes)` and status at index 7 — verify both). Add an empty `experiments/__init__.py` so the test import works.

**Known failure modes — diagnose, don't misread:**
- If `create_job` itself reverts, the likely cause is client==provider being forbidden on the (possibly newer) testnet kernel — the mainnet kernel allows it (empirically: mainnet job 56583 has identical client and provider). Fallback: derive a third throwaway account C, fund it with 0.005 tBNB from the client, and pass C as `provider` (C then signs the `submit`). A `create_job` revert says NOTHING about instant settlement — only a revert on `complete` answers E1's question.
- `requestTokens()` may revert if the faucet has a per-address cooldown; a prior successful claim already holding ≥0.01 $U makes the call unnecessary (the script checks balance first).

- [ ] **Step 4: Run the helper tests**

```bash
python -m pytest tests/test_e1_helpers.py -q
```
Expected: PASS (2 passed).

- [ ] **Step 5 (user-gated): fund the client key**

Generate a fresh throwaway key pair locally (`python -c "from eth_account import Account; a=Account.create(); print(a.address)"` — key printed only to the operator's terminal, exported as env var). USER ACTION: fund that address with ~0.05 tBNB at https://testnet.bnbchain.org/faucet-smart. Do not proceed until funded.

- [ ] **Step 6: Run the experiment**

```bash
cd "."
E1_CLIENT_KEY=... E1_EVALUATOR_KEY=... python -m experiments.e1_instant_settlement
```
Expected: `e1-result.json` written either way. If `complete` reverts, capture the revert reason — try once more with `complete(job_id, "accepted", opt)` variants ONLY if the ABI showed a different signature in Step 1; otherwise record and stop. Two identical reverts = answer is no; do not loop.

- [ ] **Step 7: Commit the result (whatever it is)**

```bash
git add experiments/e1_instant_settlement.py experiments/__init__.py tests/test_e1_helpers.py experiments/e1-result.json
git commit -m "experiment(e1): marketplace-evaluator instant settlement on testnet — result recorded"
```

---

### Task 3: SOLVENT registration JSON + content negotiation (solvent repo)

**Files:**
- Create: `web/agent-registration.json` (in `<solvent-repo>`)
- Modify: `ops/solvent.gudman.xyz.conf` (add `location = /` negotiation block above the existing `location /` at line 165)
- Test: `tests/test_agent_registration.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `https://solvent.gudman.xyz/agent-registration.json` (always) and JSON at `/` when `Accept: application/json` — the artifact 8004scan's parser needs. Registration content is the source of truth for SOLVENT's Docket listing later.

- [ ] **Step 1: Write the failing test `tests/test_agent_registration.py`**

```python
import json
from pathlib import Path

REG = Path(__file__).resolve().parents[1] / "web" / "agent-registration.json"


def test_registration_exists_and_parses():
    doc = json.loads(REG.read_text())
    assert doc["type"] == "https://eips.ethereum.org/EIPS/eip-8004#registration-v1"


def test_registration_binds_agent_136384_on_bsc():
    doc = json.loads(REG.read_text())
    regs = doc["registrations"]
    assert {"agentId": 136384,
            "agentRegistry": "eip155:56:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"} in regs


def test_registration_urls_are_https_and_ours():
    doc = json.loads(REG.read_text())
    assert doc["url"] == "https://solvent.gudman.xyz"
    for svc in doc["services"]:
        assert svc["endpoint"].startswith("https://solvent.gudman.xyz")


def test_registration_makes_no_performance_claims():
    text = REG.read_text().lower()
    for banned in ("guaranteed", "profit", "apy", "returns"):
        assert banned not in text
```

Run: `cd <solvent-repo> && python -m pytest tests/test_agent_registration.py -q` → Expected: FAIL (file missing).

- [ ] **Step 2: Write `web/agent-registration.json`**

```json
{
  "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
  "name": "SOLVENT",
  "description": "Glass-box autonomous trading agent on BNB Smart Chain. Every decision is a hash-chained receipt; the chain head is anchored daily as ERC-8004 metadata under this identity. Anyone can recompute the public log and check it against the on-chain anchors.",
  "url": "https://solvent.gudman.xyz",
  "image": "https://solvent.gudman.xyz/og.png",
  "active": true,
  "version": "0.1.0",
  "agent_type": "trading",
  "categories": ["trading", "analytics"],
  "tags": ["glass-box", "decision-receipts", "erc-8004", "bsc", "regime-signal"],
  "skills": [
    {
      "id": "daily-regime-signal",
      "name": "Daily regime signal",
      "description": "Verifiable market-regime read (risk-on/risk-off) whose signal_hash binds to the latest receipt, chain head, and anchor."
    }
  ],
  "services": [
    {
      "name": "receipts-api",
      "description": "Read-only glass-box API: hash-chained receipts, live chain verification, anchors, policy compliance.",
      "protocol": "Web",
      "endpoint": "https://solvent.gudman.xyz/verify"
    },
    {
      "name": "regime-signal",
      "description": "Latest daily regime signal payload with receipt-bound signal_hash.",
      "protocol": "Web",
      "endpoint": "https://solvent.gudman.xyz/signal"
    }
  ],
  "x402Support": true,
  "supportedTrust": ["reputation"],
  "registrations": [
    {
      "agentId": 136384,
      "agentRegistry": "eip155:56:0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"
    }
  ],
  "documentation": "https://github.com/Ridwannurudeen/solvent",
  "limitations": "Capital-preservation barbell, not an alpha claim. Receipts after the last daily anchor are recompute-consistent but not yet on-chain-bound. Historical record; live status is reported honestly at /state.",
  "updatedAt": "2026-08-06T00:00:00Z"
}
```

Then run the tests: `python -m pytest tests/test_agent_registration.py -q` → Expected: PASS (4 passed).

- [ ] **Step 3: Add the negotiation block to `ops/solvent.gudman.xyz.conf`**

Insert ABOVE the existing `location /` block (line 164 comment "The glass-box dashboard"):

```nginx
    # ERC-8004 registration at the tokenURI root. Inverted negotiation:
    # browsers always send text/html first and keep the dashboard; everything
    # else (curl/python "*/*", "application/json", header-less indexer
    # fetchers — 8004scan's parser's Accept header is unknown) gets the
    # registration JSON. rewrite...last inside if is one of nginx's safe ifs.
    location = / {
        if ($http_accept !~* "text/html") {
            rewrite ^ /agent-registration.json last;
        }
        try_files /index.html =404;
    }
```

(The existing `location /` at line 165 stays for all other paths; exact-match `location = /` wins for the root. The inversion matters: serving JSON only on `Accept: application/json` would still hand HTML to a `*/*` fetcher — the most common script default — and the re-parse would fail exactly as it does today.)

- [ ] **Step 4: Run the full solvent suite (guard against collateral damage)**

```bash
cd <solvent-repo> && python -m pytest -q
```
Expected: PASS (same count as before this task, +4).

- [ ] **Step 5: Commit (solvent repo, current branch)**

```bash
cd <solvent-repo>
git add web/agent-registration.json tests/test_agent_registration.py ops/solvent.gudman.xyz.conf
git commit -m "feat: ERC-8004 registration JSON + root content negotiation for indexers"
```

- [ ] **Step 6 (USER-APPROVAL-GATED): deploy the two changed files to the VPS**

Ship individually (never a directory copy). Find the live vhost path first; count `nginx -t` warnings against the 22-warning baseline:

```bash
ssh <deploy-user>@<vps-host> "nginx -T 2>/dev/null | grep -n 'solvent.gudman.xyz.conf' | head -3"
scp <solvent-repo>/web/agent-registration.json <deploy-user>@<vps-host>:/var/www/solvent/agent-registration.json
scp <solvent-repo>/ops/solvent.gudman.xyz.conf <deploy-user>@<vps-host>:<live-vhost-path>
ssh <deploy-user>@<vps-host> "nginx -t && systemctl reload nginx"
```

- [ ] **Step 7: Verify live from outside**

```bash
curl -s https://solvent.gudman.xyz/ | python -m json.tool | head -5
curl -s -H "Accept: application/json" https://solvent.gudman.xyz/ | python -m json.tool | head -5
curl -s -o /dev/null -w "%{content_type}\n" -H "Accept: text/html,application/xhtml+xml" https://solvent.gudman.xyz/
```
Expected: registration JSON for the first two (bare curl sends `*/*` → JSON under the inverted rule); `text/html` for the browser-style Accept. Also confirm the dashboard still renders in a real browser.

- [ ] **Step 8 (USER ACTION): request re-index**

Send to t.me/ERC8004 (draft): "Hi — agent 56:0x8004A169…:136384 (SOLVENT) now serves its registration-v1 JSON at its tokenURI (content-negotiated; also at https://solvent.gudman.xyz/agent-registration.json). It was minted 2026-06-16 and parse_status shows it was never re-parsed — could you trigger a re-parse? Happy to adjust the document if anything fails validation."

- [ ] **Step 9: Watch for the re-parse; arm the fallback on a date gate**

Check daily (cheap, unauthenticated):

```bash
curl -s "https://8004scan.io/api/v1/public/agents/56/136384" | python -c "import sys,json; d=json.load(sys.stdin)['data']; print(d['name'], d['parse_status']['last_parsed_at'])"
```
Success: `name` becomes `SOLVENT` and `last_parsed_at` moves past 2026-06-16.
**Date gate — if not re-parsed by Aug 13:** prepare the on-chain fallback (repoint `tokenURI`/agentURI to `https://solvent.gudman.xyz/agent-registration.json` — one transaction from the agent-owner wallet `0xe4fe23…d359` via the TWAK keychain on the VPS, mirroring `solvent/receipts/anchor.py`'s registry-write pattern). Present the exact command and cost to the user for approval before sending; one send, verified by re-reading `tokenURI` afterward. Docket's own listing renders SOLVENT from its enrichment pipeline regardless, so the explorer fix is upside, never a Phase-1 blocker.

---

### Task 2b: E1-revised — identify the hook revert and close E1 by simulation (added 2026-08-07)

**Files:**
- Create: `abis/EvaluatorRouter.json` (vendor from the same bnbagent-sdk source as Task 1; the testnet router/hook is `0xD7d36D66d2F1B608A0F943f722D27e3744f66F25`)
- Create: `experiments/e1b_simulate_router_flow.py`
- Modify: `experiments/e1-result.json` conventions unchanged — e1b writes `experiments/e1b-result.json` with the same key set plus `"method": "eth_simulateV1"`
- Test: extend `tests/test_e1_helpers.py`

**Context (why this task exists):** Task 2's read-only probes proved `hook = 0` reverts `HookRequired()` and the router-hook reverts direct `fund()` with un-named selector `0x32d53d69` even for genuine router jobs. `complete()` is evaluator-only; EOA evaluators are accepted at creation. The open question is whether the hook's callbacks allow a non-router **evaluator** to complete a router-registered job.

- [ ] **Step 1:** Vendor `EvaluatorRouter.json` (and any hook/policy ABI shipped beside it) exactly as Task 1 vendored the kernel ABI; extend the selector map in `_decode_error`'s source ABIs so `0x32d53d69` gets a name if it lives in these ABIs. Add a test asserting the union selector table now resolves `0x32d53d69` (if it does not, record the raw selector as a named constant `HOOK_FUND_GATE = "0x32d53d69"` with a comment stating it remains unidentified).
- [ ] **Step 2:** Write `e1b_simulate_router_flow.py`: build the full canonical sequence — `createJob(provider, evaluator=EOA_B, expiredAt, desc, hook=router)`, `router.registerJob(jobId, policy)` (policy `0x4F4678D4439feC812Ac7674Bb3Efb4C8f5Fb78A6`), `setBudget`, `approve`, `fund`, `submit`, then `complete(jobId, reason32, b"")` from EOA_B — as one `eth_simulateV1` call with balance and $U-allowance state overrides, no real keys or funds. Record per-call success/revert (decoded) into `e1b-result.json`; `worked` = the final `complete` call succeeding for the EOA evaluator.
- [ ] **Step 3:** Run it (read-only; no funding gate). Commit script + result: `experiment(e1b): router-flow simulation — EOA-evaluator settlement result recorded`.
- [ ] **Step 4:** If simulateV1 is unsupported by the RPC, fall back to sequential `eth_call` with state overrides per step (the technique Task 2 already used successfully) and note the method in the result file.

### Task 4: SOLVENT repo housekeeping — default branch → `main`

**Files:** none (GitHub + local git state only)

**Interfaces:** none. Cosmetic-but-visible: judges open this repo.

- [ ] **Step 1: Rename the default branch on GitHub and locally**

```bash
cd <solvent-repo>
git branch -m codex/solvent-private-prep main
git push -u origin main
gh api repos/Ridwannurudeen/solvent -X PATCH -f default_branch=main
git push origin --delete codex/solvent-private-prep
```

- [ ] **Step 2: Verify**

```bash
gh api repos/Ridwannurudeen/solvent --jq .default_branch
```
Expected: `main`.

---

## Self-review (done at write time)

- Spec coverage: Phase-0 items from the spec §6 all present (E1 → Task 2; SOLVENT fix + re-parse → Task 3; branch rename → Task 4; scaffold → Task 1). Registration-form drafting and 8004scan Pro form are user actions tracked in the spec, not code tasks.
- Placeholders: none; every step has runnable content. Two deliberate verify-don't-trust steps (ABI signatures, vhost path) are instructions to read a source, not gaps.
- Type consistency: `canonical_manifest_hash`/`STATUS` names match between test and module; ABI filenames consistent across Tasks 1–2.
