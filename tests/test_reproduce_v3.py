import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reproduce-v3-04.py"
JUDGE_GUIDE = ROOT / "docs" / "submission" / "judge-start-here.md"


def test_v3_04_reproducer_matches_the_documented_output():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    expected = {
        "agent_recall": {"numerator": 4, "denominator": 8, "value": 0.5},
        "manual_recall": {"numerator": 6, "denominator": 8, "value": 0.75},
        "agent_critical_failures": 3,
        "complete_pairs": 11,
        "planned_pairs": 12,
        "median_seconds_saved": 27.86,
        "median_agent_to_manual_ratio": 0.06104344152643808,
    }
    assert json.loads(completed.stdout) == expected
    assert json.dumps(expected, indent=2) in JUDGE_GUIDE.read_text(encoding="utf-8")
