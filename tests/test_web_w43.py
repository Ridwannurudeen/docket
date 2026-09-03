import json
import re
from pathlib import Path

from docket.advantage.v2 import report as v2_report
from docket.advantage.v3 import report as v3_report

WEB = Path(__file__).resolve().parents[1] / "docket" / "api" / "web"


def _home() -> str:
    return (WEB / "index.html").read_text(encoding="utf-8")


def _plain(markup: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", markup).split())


def test_public_case_file_has_the_fixed_section_order_and_labelled_sections():
    home = _home()
    section_ids = (
        "evidence",
        "experiments",
        "adverse-case",
        "receipt",
        "services",
        "case-close",
    )

    offsets = [home.index(f'id="{section_id}"') for section_id in section_ids]
    assert offsets == sorted(offsets)
    for section_id in section_ids:
        section = re.search(
            rf'<section[^>]+id="{section_id}"[^>]*>', home
        ).group(0)
        assert "aria-labelledby=" in section


def test_hero_uses_the_approved_copy_and_keeps_both_actions_above_the_truth_rail():
    home = _home()
    hero = re.search(r'<section class="case-hero".*?</section>', home, re.S).group(0)
    rail = re.search(r'<aside class="truth-rail".*?</aside>', home, re.S).group(0)
    rail_text = _plain(rail)

    assert "DOCKET / EVIDENCE-FIRST AGENT MARKETPLACE" in hero
    assert "Hire by evidence, not promises." in hero
    assert "We measured our own security agent against a human. The human won." in hero
    assert "It is on the front page." in hero
    assert ">Inspect the evidence<" in hero
    assert ">Run Range Doctor<" in hero
    assert "6 services" in rail_text
    assert "0 paid stock" in rail_text
    assert "0 settlements ever run" in rail_text
    assert hero.index("hero-copy") < hero.index("truth-rail") < hero.index("hero-finding")
    assert home.index("case-hero") < home.index("truth-rail")


def test_decision_impact_copy_matches_the_report_rounding_and_denominators():
    impact = v2_report.report()["decision_impact"]
    notional = impact["dollars_at_notionals"]["notionals"][0]
    reversals = impact["ranking_reversals"]
    delay = impact["break_even_shift"]
    home = _home()

    assert notional["notional_usd"] == 10000.0
    assert notional["n_pools"] == 22
    assert f'${notional["median_annual_overstatement_usd"]:.2f}' in home
    assert f'n={notional["n_pools"]}' in home
    assert f'{delay["median_days_later_than_gross_implies"]:.2f} days' in home
    assert f'{reversals["numerator"]}/{reversals["denominator"]}' in home
    assert f'({reversals["value"]:.2%})' in home


def test_adverse_case_is_not_softened_into_a_scored_verdict():
    family = next(
        family
        for family in v3_report.report()["families"]
        if family["spec_id"] == "v3-04-warden-security"
    )
    home = _home()
    case = re.search(
        r'<section[^>]+id="adverse-case".*?</section>', home, re.S
    ).group(0)

    assert family["state"] == "complete_unscored"
    assert family["run_progress"] == {
        "scheduled_primaries": 24,
        "claimed_primaries": 24,
        "terminal_primaries": 24,
        "outcomes": {"failed": 1, "succeeded": 23},
    }
    assert "Case 01 — Warden lost the recall test." in case
    assert "Warden" in case and "4/8" in case and "0.50" in case
    assert "Human" in case and "6/8" in case and "0.75" in case
    assert "Three critical Warden failures." in case
    assert "24/24 primaries terminal" in case
    assert "23 succeeded · 1 manual failure" in case
    assert "rubric permanently unscored" in case
    assert "complete_unscored" in case
    assert "not a scored verdict" in case


def test_range_receipt_keeps_the_digest_and_reproduction_bound_together():
    frame = (
        Path(__file__).resolve().parents[1]
        / "docket"
        / "advantage"
        / "v3"
        / "sources"
        / "range-v5-enumerable-frame.json"
    )
    receipt = re.search(r'<section[^>]+id="receipt".*?</section>', _home(), re.S).group(0)
    digest = "ea41a6391e2d40f15c394224d9c7b0699b3eeca4968a2de9f75c43df32469761"

    assert len(json.loads(frame.read_text(encoding="utf-8"))["rows"]) == 1024
    assert digest in receipt
    assert "1,024-row Range frame" in receipt
    assert "Exact byte-for-byte rehearsal match." in receipt
    assert "Rehearsal · 24 Aug 2026" in receipt
    assert "Registered frame · committed 28 Aug 2026" in receipt
    assert receipt.count(digest) == 3


def test_case_file_stays_restrained_and_uses_the_agreed_tokens():
    home = _home().lower()
    css = (WEB / "style.css").read_text(encoding="utf-8")

    for forbidden in (
        "testimonial",
        "trusted by",
        "logo-strip",
        "animated-counter",
        "dashboard",
    ):
        assert forbidden not in home
    assert "linear-gradient" not in css
    assert "radial-gradient" not in css
    for token in (
        "--bg: #f4f1e8",
        "--fg: #161816",
        "--border: #cbc8be",
        "--accent: #1f614b",
        "--danger: #963e2f",
        '--serif: Georgia, "Times New Roman", serif',
    ):
        assert token in css
    assert ".case-file-page" in css
    assert "font-variant-numeric: tabular-nums" in css
