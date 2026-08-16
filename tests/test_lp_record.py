"""The daily record of the controlled position.

The behaviour worth pinning is not that a good day is written down. It is that a bad day is
written down too — an unreachable endpoint has to leave a line saying so, because a gap in
an append-only file reads exactly like nobody having run it, and a reader auditing the
history months later cannot tell those apart.
"""

import json
from datetime import datetime, timezone

import pytest

from docket.agents.pancake import lp_record

WALLET = "0xe55816904796341bf8535e25f6c8b647927fc946"
TOKEN = 7141050
WHEN = datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc)


def _report(**overrides):
    body = {
        "address": WALLET,
        "target_token_id": TOKEN,
        "target_found": True,
        "positions_held": 1,
        "positions_examined": 1,
        "closed_skipped": 0,
        "scan_complete": True,
        "positions": [{"position": {"token_id": TOKEN}}],
    }
    return body | overrides


def test_a_successful_day_records_the_product_s_own_output():
    record = lp_record.observe(
        WALLET,
        TOKEN,
        declared_position_value_usd=50.55,
        reporter=lambda *a, **k: _report(),
        now=WHEN,
    )
    assert record["observed"] is True
    assert record["still_held"] is True
    assert record["target_found"] is True
    assert record["observed_at"] == "2026-08-16T06:00:00+00:00"
    # The report travels whole rather than being summarised into this file's own vocabulary.
    assert record["report"]["target_token_id"] == TOKEN


def test_an_unreachable_endpoint_still_leaves_a_line():
    """The point of the file. A day with no line cannot be told from a day nobody ran."""

    def _raise(*_args, **_kwargs):
        raise RuntimeError("every BSC endpoint failed")

    record = lp_record.observe(WALLET, TOKEN, reporter=_raise, now=WHEN)
    assert record["observed"] is False
    assert "every BSC endpoint failed" in record["error"]
    assert record["observed_at"] == "2026-08-16T06:00:00+00:00"
    assert "report" not in record


def test_a_closed_or_transferred_position_is_visible_rather_than_absent():
    record = lp_record.observe(
        WALLET,
        TOKEN,
        reporter=lambda *a, **k: _report(
            target_found=False, positions_held=0, positions=[]
        ),
        now=WHEN,
    )
    assert record["observed"] is True
    assert record["still_held"] is False
    assert record["target_found"] is False


def test_the_history_is_append_only(tmp_path):
    path = tmp_path / "lp" / "controlled.jsonl"
    first = lp_record.observe(
        WALLET, TOKEN, reporter=lambda *a, **k: _report(), now=WHEN
    )
    lp_record.append(first, path)

    def _raise(*_args, **_kwargs):
        raise RuntimeError("endpoints down")

    lp_record.append(lp_record.observe(WALLET, TOKEN, reporter=_raise, now=WHEN), path)

    history = lp_record.read(path)
    assert [entry["observed"] for entry in history] == [True, False]
    # The first day is untouched by the second being written.
    assert history[0]["report"]["target_token_id"] == TOKEN
    assert path.read_text(encoding="utf-8").count("\n") == 2


def test_reading_a_history_that_does_not_exist_yet_is_not_an_error(tmp_path):
    assert lp_record.read(tmp_path / "never-written.jsonl") == []


@pytest.mark.parametrize(
    "reporter, expected",
    [
        (lambda *a, **k: _report(), 0),
        (lambda *a, **k: _report(target_found=False, positions_held=0), 1),
    ],
    ids=["found", "not-found"],
)
def test_the_timer_learns_whether_the_day_produced_a_diagnosis(
    tmp_path, monkeypatch, reporter, expected
):
    """A recorded failure is still a failure the unit should see."""
    monkeypatch.setattr(lp_record.doctor, "report", reporter)
    path = tmp_path / "controlled.jsonl"
    code = lp_record.main(
        [WALLET, str(TOKEN), str(path), "--declared-value-usd", "50.55"]
    )
    assert code == expected
    assert len(lp_record.read(path)) == 1


def test_a_recorded_line_is_canonical_json(tmp_path):
    """The history is evidence, so its bytes have to be stable across writers."""
    path = tmp_path / "controlled.jsonl"
    lp_record.append(
        lp_record.observe(WALLET, TOKEN, reporter=lambda *a, **k: _report(), now=WHEN),
        path,
    )
    line = path.read_text(encoding="utf-8").splitlines()[0]
    assert line == json.dumps(json.loads(line), sort_keys=True)


def test_a_transferred_position_is_not_hidden_by_the_wallet_holding_others():
    """The one day this record exists to catch, previously reported as a normal day.

    `still_held` read the wallet's total position count, so a wallet that had moved the
    tracked NFT away but still held any other one recorded `still_held: true`. The record
    is about token 7141050, not about how busy its owner is.
    """
    record = lp_record.observe(
        WALLET,
        TOKEN,
        reporter=lambda *a, **k: _report(
            target_found=False, positions_held=3, positions=[]
        ),
        now=WHEN,
    )
    assert record["still_held"] is False
    assert record["target_found"] is False
    # The wallet's own count is kept, because it is a fact — just not this one.
    assert record["wallet_positions_held"] == 3
