# Docket Phase 1f — Hire Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Docket's agents actually hireable — a stranger's coding agent lands, discovers a service, calls it, and gets real work back, first try. TermiX judges by doing exactly that.

**Architecture:** A service catalogue over the agents Docket owns, a `POST /hire/{service_id}` endpoint that runs the work and returns a hash-bound receipt, and an x402 payment layer that is *additive*: the free tier always works, so a cold hire can never fail because of payment plumbing. Payment authorizations are verified cryptographically with the already-pinned `eth_account`; settlement is a separate, explicitly-labelled concern.

**Tech Stack:** Existing pins only — `fastapi==0.137.1`, `eth-account==0.13.7`, `web3==7.16.0`, stdlib. No new dependencies.

## Global Constraints

- **A cold hire must succeed with no setup.** No account, no key, no wallet, no API key for the free tier. TermiX's evaluator agents fail closed on friction; a 402 wall on first contact loses 30% of their rubric.
- **Never claim settlement Docket did not perform.** Docket can verify an EIP-712 payment authorization (verified working with the pinned `eth_account` 0.13.7 — sign and recover round-trips). It does **not** broadcast or settle. Every payment-bearing response states its true status: `verified_unsettled`, never "paid".
- x402 challenge shape, per the verified BSC dialect: `x402Version: 2`, `accepts[].scheme: "exact"`, `network: "eip155:56"`, `maxTimeoutSeconds <= 480`, and `extra.assetTransferMethod` carrying the rail (`permit2-exact` is ranked first on BSC because EIP-3009 needs an ERC-1271-aware token and Binance-Peg USDC is not one). Read the header from `X-PAYMENT`, falling back to `PAYMENT-SIGNATURE`.
- **Fail safe on configuration.** If `DOCKET_PAY_TO` is unset, the paid tier is disabled and the free tier still serves. A missing config must never break hiring.
- **Every deliverable is hash-bound.** A receipt carries `input_hash`, `output_hash`, `service`, `delivered_at`, and the payment status. Canonical JSON: sorted keys, no spaces, UTF-8, SHA-256. A caller must be able to recompute both hashes from what they sent and received.
- **No verdict language**, consistent with the rest of Docket. A receipt records what was delivered; it does not assert the work was correct or the agent is good.
- Rate limiting on the free tier is per-IP, bounded, and states its limit in the 429 body so a caller can back off intelligently rather than guess.
- No Claude/Anthropic attribution; no Co-Authored-By. Stage by explicit filename. Do not push.
- Repo `C:\Users\gudma\OneDrive\Desktop\GITHUB-FILES\docket`, run with `./.venv/Scripts/python`.

## File Structure

```
docket/hire/__init__.py
docket/hire/catalogue.py   # the services Docket offers, with prices and delivery claims
docket/hire/receipts.py    # canonical hashing + receipt construction
docket/hire/x402.py        # challenge builder + EIP-712 authorization verifier
docket/api/routes.py       # MODIFY: GET /hire, POST /hire/{service_id}
tests/test_hire_catalogue.py
tests/test_hire_receipts.py
tests/test_hire_x402.py
tests/test_hire_api.py
```

---

### Task 1: Catalogue and receipts

**Files:** Create `docket/hire/__init__.py`, `docket/hire/catalogue.py`, `docket/hire/receipts.py`, `tests/test_hire_catalogue.py`, `tests/test_hire_receipts.py`

**Interfaces:**
- `SERVICES: dict[str, Service]` and `get_service(service_id) -> Service | None`. A `Service` carries `id`, `name`, `what_you_get`, `input_schema` (a plain dict describing required fields), `typical_seconds`, `price_display`, `price_atomic`, `asset`, and `run(payload) -> dict`.
- `canonical_hash(obj) -> str` (`"0x…"`, SHA-256 over canonical JSON) and `build_receipt(service_id, request_payload, result, *, payment) -> dict`.

**The first service is `range-doctor`:** input `{"wallet": "0x…", "limit": int|null}`, output the Phase 1e report. It is genuinely useful, needs no credentials from the caller, and completes in tens of seconds.

- [ ] **Step 1: Write `tests/test_hire_receipts.py`**

```python
import json

from docket.hire.receipts import build_receipt, canonical_hash


def test_canonical_hash_is_key_order_independent():
    a = canonical_hash({"b": 1, "a": {"y": 2, "x": [1, 2]}})
    b = canonical_hash({"a": {"x": [1, 2], "y": 2}, "b": 1})
    assert a == b
    assert a.startswith("0x") and len(a) == 66


def test_canonical_hash_changes_when_content_changes():
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


def test_canonical_hash_is_recomputable_by_a_third_party():
    """A caller must be able to verify the hash without Docket's code."""
    import hashlib

    obj = {"wallet": "0xabc", "limit": 5}
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert canonical_hash(obj) == "0x" + hashlib.sha256(blob).hexdigest()


def test_receipt_binds_input_and_output():
    payload = {"wallet": "0xabc"}
    result = {"positions": []}
    r = build_receipt("range-doctor", payload, result, payment={"status": "free_tier"})
    assert r["service"] == "range-doctor"
    assert r["input_hash"] == canonical_hash(payload)
    assert r["output_hash"] == canonical_hash(result)
    assert r["delivered_at"].endswith("+00:00")
    assert r["payment"]["status"] == "free_tier"


def test_receipt_never_claims_settlement_it_did_not_perform():
    r = build_receipt("range-doctor", {}, {}, payment={"status": "verified_unsettled"})
    assert r["payment"]["status"] == "verified_unsettled"
    assert "paid" not in json.dumps(r).lower()
```

- [ ] **Step 2: Write `tests/test_hire_catalogue.py`**

```python
from docket.hire.catalogue import SERVICES, get_service


def test_range_doctor_is_offered_and_describes_itself():
    svc = get_service("range-doctor")
    assert svc is not None
    assert svc.what_you_get and svc.typical_seconds > 0
    assert "wallet" in svc.input_schema


def test_unknown_service_returns_none():
    assert get_service("nope") is None


def test_every_service_states_a_price_and_an_asset():
    for svc in SERVICES.values():
        assert svc.price_display and svc.price_atomic and svc.asset


def test_no_service_promises_an_outcome():
    """Docket sells work performed, not results achieved."""
    banned = ("guaranteed", "profit", "best", "safe", "will increase", "recommended")
    for svc in SERVICES.values():
        blob = f"{svc.name} {svc.what_you_get}".lower()
        for word in banned:
            assert word not in blob, f"{svc.id} promises: {word}"
```

- [ ] **Step 3: Write both modules.** `canonical_hash` uses `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")` then SHA-256. `Service` is a frozen dataclass; `run` for `range-doctor` calls `docket.agents.pancake.doctor.report` with the payload's `wallet` and `limit` (default `limit=10` so a hire returns in tens of seconds rather than minutes — the 155-position case measured ~5 minutes unbounded).

- [ ] **Step 4: Run** both test files → 9 passed. Full suite → 145 passed.

- [ ] **Step 5: Commit** `git commit -m "feat(hire): service catalogue and hash-bound delivery receipts"`

---

### Task 2: x402 challenge and authorization verification

**Files:** Create `docket/hire/x402.py`, `tests/test_hire_x402.py`

**Interfaces:** `build_challenge(service, pay_to, *, resource) -> dict`; `parse_payment_header(headers) -> dict | None`; `verify_authorization(auth, *, expected_to, expected_value, chain_id=56) -> tuple[bool, str]` returning `(ok, reason)` with `OK = "ok"`.

**What this layer does and does not do:** it proves a caller signed an EIP-712 authorization that pays the right recipient the right amount on the right chain, and that it has not expired. It does **not** broadcast, settle, or check the payer's balance. Every code path that reports success must say `verified_unsettled`.

- [ ] **Step 1: Write `tests/test_hire_x402.py`**

```python
import time

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from docket.hire.catalogue import get_service
from docket.hire.x402 import OK, build_challenge, parse_payment_header, verify_authorization

PAY_TO = "0x" + "11" * 20
ASSET = "0xcE24439F2D9C6a2289F741120FE202248B666666"


def _signed(acct, *, to=PAY_TO, value=10**16, valid_before=None, chain_id=56):
    domain = {"name": "United Stables", "version": "1",
              "chainId": chain_id, "verifyingContract": ASSET}
    types = {"TransferWithAuthorization": [
        {"name": "from", "type": "address"}, {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"}, {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"}, {"name": "nonce", "type": "bytes32"}]}
    msg = {"from": acct.address, "to": to, "value": value, "validAfter": 0,
           "validBefore": valid_before or int(time.time()) + 300, "nonce": b"\x02" * 32}
    sig = acct.sign_message(encode_typed_data(domain, types, msg))
    return {"domain": domain, "types": types, "message": {**msg, "nonce": "0x" + "02" * 32},
            "signature": sig.signature.hex()}


def test_challenge_declares_the_verified_bsc_dialect():
    ch = build_challenge(get_service("range-doctor"), PAY_TO, resource="https://d/hire/range-doctor")
    assert ch["x402Version"] == 2
    offer = ch["accepts"][0]
    assert offer["scheme"] == "exact"
    assert offer["network"] == "eip155:56"
    assert offer["payTo"] == PAY_TO
    assert offer["maxTimeoutSeconds"] <= 480      # Studio signers refuse longer windows
    assert "assetTransferMethod" in offer["extra"]


def test_valid_authorization_verifies():
    acct = Account.create()
    ok, reason = verify_authorization(_signed(acct), expected_to=PAY_TO, expected_value=10**16)
    assert ok is True and reason == OK


def test_wrong_recipient_is_rejected():
    acct = Account.create()
    auth = _signed(acct, to="0x" + "22" * 20)
    ok, reason = verify_authorization(auth, expected_to=PAY_TO, expected_value=10**16)
    assert ok is False and "recipient" in reason


def test_short_payment_is_rejected():
    acct = Account.create()
    auth = _signed(acct, value=1)
    ok, reason = verify_authorization(auth, expected_to=PAY_TO, expected_value=10**16)
    assert ok is False and "amount" in reason


def test_expired_authorization_is_rejected():
    acct = Account.create()
    auth = _signed(acct, valid_before=int(time.time()) - 10)
    ok, reason = verify_authorization(auth, expected_to=PAY_TO, expected_value=10**16)
    assert ok is False and "expired" in reason


def test_wrong_chain_is_rejected():
    """A signature valid on another chain must not buy anything here."""
    acct = Account.create()
    auth = _signed(acct, chain_id=1)
    ok, reason = verify_authorization(auth, expected_to=PAY_TO, expected_value=10**16)
    assert ok is False and "chain" in reason


def test_tampered_message_fails_recovery():
    acct = Account.create()
    auth = _signed(acct)
    auth["message"]["value"] = 10**18          # inflate after signing
    ok, reason = verify_authorization(auth, expected_to=PAY_TO, expected_value=10**18)
    assert ok is False


def test_header_is_read_from_either_spelling():
    import base64, json as _json
    blob = base64.b64encode(_json.dumps({"a": 1}).encode()).decode()
    assert parse_payment_header({"x-payment": blob}) == {"a": 1}
    assert parse_payment_header({"payment-signature": blob}) == {"a": 1}
    assert parse_payment_header({}) is None


def test_malformed_header_returns_none_rather_than_raising():
    assert parse_payment_header({"x-payment": "not-base64!!"}) is None
```

- [ ] **Step 2: Write `x402.py`.** `verify_authorization` recovers the signer with `Account.recover_message(encode_typed_data(...), signature=...)` — a tampered message changes the digest, so recovery yields a different address and the check fails naturally. Verify, in order and returning the first failure: chain id, recipient, amount (>= expected), expiry, then signature recovery. `parse_payment_header` base64-decodes and JSON-parses, returning `None` on any malformation rather than raising.

- [ ] **Step 3: Run** → 9 passed. Full suite → 154 passed.

- [ ] **Step 4: Commit** `git commit -m "feat(hire): x402 challenge and EIP-712 authorization verification"`

---

### Task 3: The hire endpoints

**Files:** Modify `docket/api/routes.py`, `docket/api/models.py`, `docket/api/static/llms.txt`, `docket/api/static/SKILL.md`; create `tests/test_hire_api.py`

**Endpoints:**

| Method | Path | Behaviour |
|---|---|---|
| GET | `/hire` | The catalogue: every service with what you get, price, typical seconds, and its input schema |
| POST | `/hire/{service_id}` | Runs the work. Free tier serves immediately; with a valid `X-PAYMENT` header records `verified_unsettled`; over the free limit without payment returns 402 with the challenge |

- [ ] **Step 1: Write `tests/test_hire_api.py`** covering: `GET /hire` lists `range-doctor` with its input schema; a `POST` with a valid wallet returns a receipt whose `input_hash` matches the caller's own recomputation; a `POST` with a missing `wallet` returns the structured error shape with a code naming the missing field; an unknown service returns 404 `service_not_found`; exceeding the free limit without payment returns **402** with a body containing `x402Version` and `accepts`; a request carrying a valid authorization is served and its receipt says `verified_unsettled`; and — the honesty test — no hire response anywhere contains the word "paid". Stub the service `run` so the suite never touches the network or takes 30 seconds.

- [ ] **Step 2: Implement.** `GET /hire` is static from the catalogue. `POST /hire/{service_id}`: resolve the service (404 with `service_not_found` if unknown) → validate the payload against `input_schema` (422 `missing_field` naming it) → check the payment header; if present and valid, run and record `verified_unsettled`; if absent, check the free-tier counter, run if under, else 402 with the challenge → build and return the receipt alongside the result. When `DOCKET_PAY_TO` is unset the paid path is disabled and the free tier serves without limit — configuration must never break hiring.

- [ ] **Step 3: Update `llms.txt` and `SKILL.md`** with the hire workflow: the catalogue, a copy-pasteable `curl` that hires Range Doctor for a wallet, what the receipt fields mean, how to recompute the hashes, and an explicit statement that a `verified_unsettled` payment status means Docket checked the signature and did not settle it. The existing drift test asserts `llms.txt` mentions every OpenAPI path, so both new paths must appear.

- [ ] **Step 4: Run** the suite → 161 passed.

- [ ] **Step 5: Commit** `git commit -m "feat(hire): catalogue and hire endpoints with additive x402"`

---

### Task 4: Cold-hire rehearsal

- [ ] **Step 1:** Serve the real store and hire Range Doctor exactly as a stranger's agent would — `curl` only, no setup, reading nothing but `/llms.txt` first:

```bash
curl -s localhost:8100/llms.txt | head -40
curl -s localhost:8100/hire
curl -s -X POST localhost:8100/hire/range-doctor \
  -H 'content-type: application/json' \
  -d '{"wallet":"0x451871A1753903FB8fdd64a6B838E95aB8D5B80f","limit":5}'
```

- [ ] **Step 2:** Verify the receipt independently: recompute `input_hash` from the request body and `output_hash` from the returned result using plain `sha256` over canonical JSON, without importing Docket. Paste both computations into the report.

- [ ] **Step 3:** Time it. Record the real wall-clock for a cold hire; if it exceeds ~60s, lower the default `limit` until it does not. Speed is explicitly part of what TermiX scores.

- [ ] **Step 4:** Commit any fixes.

---

## Self-review (done at write time)

- Spec coverage: this is the "hire" leg of find→compare→hire, the hard gate the Agent Advantage Report depends on, and it is deliberately built so the free tier alone satisfies a cold evaluator.
- The settlement boundary is enforced by a test asserting the word "paid" never appears in a hire response — the exact overclaim this project must not make.
- Receipt hashes are third-party recomputable, with a test that recomputes one using only stdlib.
- Placeholders: none. Task 3 describes handlers in prose but every status code, error code, and field the tests pin is named exactly.
