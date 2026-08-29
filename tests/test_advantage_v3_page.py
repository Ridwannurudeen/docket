"""Public v3 labels must describe who actually produced each arm."""

from docket.advantage.v3 import page


def test_assisted_baseline_uses_registered_public_arm_names():
    rendered = page._arms(
        {
            "arms": {
                "manual": {
                    "display_name": "Codex-assisted baseline",
                    "what_it_does": "answers the synthetic task",
                    "who_runs_it": "Codex",
                    "what_is_recorded": "the first output",
                },
                "agent": {
                    "display_name": "Deployed Yield Router",
                    "what_it_does": "answers the same task",
                    "who_runs_it": "the deployed service",
                    "what_is_recorded": "the first output",
                },
            }
        }
    )

    assert "Codex-assisted baseline arm" in rendered
    assert "Deployed Yield Router arm" in rendered
    assert ">Manual arm<" not in rendered


def test_legacy_arms_keep_their_existing_labels():
    arm = {
        "what_it_does": "does the task",
        "who_runs_it": "the registered runner",
        "what_is_recorded": "the output",
    }
    rendered = page._arms({"arms": {"manual": arm, "agent": arm}})

    assert "Manual arm" in rendered
    assert "Agent arm" in rendered
