from pathlib import Path

import pytest

from orchestra_runtime import OrchestraRuntime


def test_runtime_task_lifecycle_and_mandates(tmp_path: Path):
    runtime = OrchestraRuntime(repo_root=tmp_path, state_root=tmp_path / ".state")

    task = runtime.start_task(
        user_goal="Review README for accuracy",
        depth_profile="standard",
        task_type="docs",
    )
    task_id = task["task_id"]

    updated = runtime.set_mandates(
        task_id,
        [
            {
                "musician": "cello",
                "title": "Read docs",
                "objective": "Identify mismatches",
            },
            {
                "musician": "harp",
                "title": "Validate claims",
                "objective": "Cross-check code behavior",
            },
        ],
    )
    assert len(updated["mandates"]) == 2

    record = runtime.create_assignment(
        task_id=task_id,
        musician="cello",
        goal="scan README",
        scope=["README.md"],
        constraints=["read only"],
        timeout_ms=30000,
    )
    runtime.update_assignment(record.assignment_id, status="in_progress")
    runtime.update_assignment(record.assignment_id, status="completed")

    rows = runtime.list_assignments(task_id, statuses=["completed"])
    assert len(rows) == 1
    assert rows[0].assignment_id == record.assignment_id

    cleared = runtime.clear_mandates(task_id)
    assert cleared["mandates"] == []


def test_runtime_rejects_invalid_or_duplicate_musicians(tmp_path: Path):
    runtime = OrchestraRuntime(repo_root=tmp_path, state_root=tmp_path / ".state")
    task_id = runtime.start_task("x", "quick", "mixed")["task_id"]

    with pytest.raises(ValueError):
        runtime.set_mandates(
            task_id,
            [
                {
                    "musician": "oboe",
                    "title": "bad",
                    "objective": "bad",
                }
            ],
        )

    with pytest.raises(ValueError):
        runtime.set_mandates(
            task_id,
            [
                {
                    "musician": "cello",
                    "title": "a",
                    "objective": "a",
                },
                {
                    "musician": "cello",
                    "title": "b",
                    "objective": "b",
                },
            ],
        )
