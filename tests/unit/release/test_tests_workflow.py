from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"


def test_frontend_build_workspace_is_removed_before_python_install() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    for job_name in ("unit-tests", "integrated-tests", "coverage-report"):
        steps = workflow["jobs"][job_name]["steps"]
        copy_step = next(
            step for step in steps if step.get("name") == "Copy console build into package"
        )
        setup_python_index = next(
            index
            for index, step in enumerate(steps)
            if str(step.get("name", "")).startswith("Set up Python")
        )
        copy_step_index = steps.index(copy_step)

        assert "rm -rf client" in copy_step["run"]
        assert copy_step_index < setup_python_index
