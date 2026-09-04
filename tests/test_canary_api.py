from fastapi.testclient import TestClient

from docket.agents.pancake import doctor
from docket.api import create_app
from docket.hire import admission as admission_module
from docket.hire import catalogue
from docket.hire.catalogue import USDT_TOKEN
from docket.hire.x402 import B402_NETWORK, B402_RELAYER, EIP712_DOMAINS
from docket.store import Store

WALLET = "0x451871A1753903FB8fdd64a6B838E95aB8D5B80f"
PAY_TO = "0x" + "11" * 20
# Wide enough that the committed v1 experiment stays inside it however long after 2026 a
# test runs, and still a real date the expiry instant can be printed from.
A_CENTURY_S = 100 * 365 * 24 * 60 * 60
PASSING_CHECK = {
    "leg": "complete_human_result",
    "checked": "the complete paid hire chain",
    "status": "passed",
    "observed": {"settlement_amount": "0.50"},
    "evidence": {"replay_status": 409},
}


def _admit_every_fact_but_the_canary(monkeypatch, store):
    """Open the three limbs this test is not about, from the state each one reads.

    The paired limb is opened by widening the disclosed freshness window rather than by
    inventing an artifact: `01-liquidity` is a real committed paired benchmark naming
    range-doctor, and widening the window keeps the fixture from depending on how far
    today is from the day it ran. `cold_canary` is left closed — it is the subject.
    """
    monkeypatch.setattr(admission_module, "PAIRED_EVIDENCE_WINDOW_SECONDS", A_CENTURY_S)
    store.reserve_payment(
        nonce="0x" + "5e" * 32,
        payment_id="0xseed",
        service_id="range-doctor",
        payer=catalogue.CONTROLLED_EXAMPLE_WALLET,
        recipient=PAY_TO,
        asset=USDT_TOKEN,
        amount=str(5 * 10**17),
        resource="http://testserver/hire/range-doctor",
        input_hash="0x" + "aa" * 32,
    )
    store.record_payment_output("0xseed", output_hash="0x" + "bb" * 32, result={})
    assert store.begin_payment_settlement("0xseed")
    store.finish_payment(
        "0xseed",
        transaction_id="0x" + "cc" * 32,
        network=B402_NETWORK,
        receipt={"settled": True},
    )


def test_canary_history_starts_empty_and_cannot_admit_paid_work(tmp_path):
    client = TestClient(create_app(tmp_path / "empty.sqlite3"))

    response = client.get("/canary")

    assert response.status_code == 200
    assert response.json()["latest"] is None
    assert response.json()["history"] == []
    assert response.json()["admission"]["cold_canary"] is False
    assert response.json()["paid_stock"] is False


def test_one_durable_verdict_controls_every_public_admission_surface_without_restart(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        doctor,
        "report",
        lambda address, **_kwargs: {
            "address": address,
            "positions": [],
            "positions_held": 0,
        },
    )
    db = tmp_path / "dynamic.sqlite3"
    store = Store(db)
    _admit_every_fact_but_the_canary(monkeypatch, store)
    client = TestClient(create_app(db))

    def public_paid_stock():
        catalogue = client.get("/hire").json()["services"]
        listing = next(item for item in catalogue if item["id"] == "range-doctor")
        marketplace = client.get("/services").json()["services"]
        card = next(
            item for item in marketplace if item["service_id"] == "range-doctor"
        )
        detail = client.get("/services/range-doctor").json()
        return listing["paid_stock"], card["paid_stock"], detail["paid_stock"]

    assert public_paid_stock() == (False, False, False)
    passed = store.begin_canary_run("range-doctor", "https://docket.example")
    store.finish_canary_run(passed, verdict="passed", checks=[PASSING_CHECK])
    assert public_paid_stock() == (True, True, True)

    running = store.begin_canary_run("range-doctor", "https://docket.example")
    assert public_paid_stock() == (False, False, False)
    preview = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": "not-a-payment"},
    )
    assert preview.status_code == 200
    assert preview.json()["receipt"]["payment"]["status"] == "not_for_sale"

    store.finish_canary_run(
        running,
        verdict="failed",
        checks=[{**PASSING_CHECK, "status": "failed"}],
    )
    assert public_paid_stock() == (False, False, False)
    history = client.get("/canary?limit=2").json()
    assert [run["verdict"] for run in history["history"]] == ["failed", "passed"]
    assert history["paid_stock"] is False


class _UnusedFacilitator:
    def verify(self, _envelope):
        raise AssertionError(
            "malformed payment must fail before facilitator verification"
        )

    def settle(self, _envelope):
        raise AssertionError("malformed payment must never settle")


def test_the_private_canary_header_opens_only_the_measured_payment_path(
    tmp_path, monkeypatch
):
    token_file = tmp_path / "canary.token"
    token_file.write_text("t" * 64, encoding="ascii")
    monkeypatch.setenv("DOCKET_CANARY_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("DOCKET_PAY_TO", "0x" + "11" * 20)
    db = tmp_path / "token.sqlite3"
    client = TestClient(create_app(db, facilitator=_UnusedFacilitator()))

    invalid = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": "invalid", "X-Docket-Canary": "wrong"},
    )
    challenge = client.post(
        "/hire/range-doctor",
        json={"wallet": WALLET},
        headers={"X-PAYMENT": "invalid", "X-Docket-Canary": "t" * 64},
    )

    assert invalid.status_code == 403
    assert invalid.json()["error"]["code"] == "canary_unauthorized"
    assert challenge.status_code == 402
    assert challenge.json()["error"]["code"] == "payment_invalid"
    offer = challenge.json()["accepts"][0]
    assert offer["amount"] == str(5 * 10**17)
    assert offer["asset"] == USDT_TOKEN
    assert offer["extra"] == {
        "assetTransferMethod": "b402-relayer",
        **EIP712_DOMAINS[USDT_TOKEN.lower()],
        "relayerContract": B402_RELAYER,
    }
    assert "t" * 64 not in str(client.get("/canary").json())
