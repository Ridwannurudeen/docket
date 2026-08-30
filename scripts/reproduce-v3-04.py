import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from docket.advantage.v3 import runner, scoring
    from docket.advantage.v3.spec import load

    spec = load(ROOT / "docket/advantage/v3/specs/v3-04-warden-security.json")
    inputs = scoring.load_inputs(spec, repo_root=ROOT)
    attempts = scoring.primary_attempts(
        spec,
        runner.ledger_path(spec, ROOT / "docket/advantage/v3/runs"),
        repo_root=ROOT,
    )
    warden = scoring.warden_metrics(spec, inputs, attempts, repo_root=ROOT)
    speed = scoring.speed_metrics(
        spec,
        attempts,
        inputs=inputs,
        repo_root=ROOT,
    )
    print(
        json.dumps(
            {
                "agent_recall": warden["arms"]["agent"]["recall"],
                "manual_recall": warden["arms"]["manual"]["recall"],
                "agent_critical_failures": len(
                    warden["arms"]["agent"]["critical_gate_failures"]
                ),
                "complete_pairs": speed["n_complete_pairs"],
                "planned_pairs": speed["n_planned_pairs"],
                "median_seconds_saved": speed["median_seconds_saved"],
                "median_agent_to_manual_ratio": speed["median_agent_to_manual_ratio"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
