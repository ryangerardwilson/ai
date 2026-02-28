import json
from pathlib import Path

from orchestra_runtime import OrchestraRuntime
from orchestra_tools import handle_orchestra_tool_call


class DummyScheduler:
    def __init__(self):
        self.dispatched = []
        self.cancelled = set()

    def dispatch(self, *, task_id, dispatch_plan, mode):
        self.dispatched.append((task_id, dispatch_plan, mode))
        return ["asg_test_1"]

    def poll(self, *, task_id, statuses=None):
        return [{"assignment_id": "asg_test_1", "task_id": task_id, "status": "completed"}]

    def wait(self, *, assignment_id, timeout_ms=None):
        return {
            "assignment_id": assignment_id,
            "status": "completed",
            "timed_out": False,
        }

    def cancel(self, *, assignment_id):
        self.cancelled.add(assignment_id)
        return True


def _call(tool_name, args, runtime, scheduler):
    text, mutated = handle_orchestra_tool_call(
        tool_name,
        args,
        runtime=runtime,
        scheduler=scheduler,
    )
    return json.loads(text), mutated


def test_compose_and_set_mandates_flow(tmp_path: Path):
    runtime = OrchestraRuntime(repo_root=tmp_path, state_root=tmp_path / ".state")
    scheduler = DummyScheduler()

    payload, mutated = _call(
        "compose_ensemble",
        {"user_goal": "Audit docs", "depth_profile": "quick"},
        runtime,
        scheduler,
    )
    assert mutated is True
    assert payload["ok"] is True
    task_id = payload["data"]["task_id"]

    mandates = payload["data"]["proposed_mandates"]
    payload2, mutated2 = _call(
        "set_musician_mandates",
        {"task_id": task_id, "mandates": mandates},
        runtime,
        scheduler,
    )
    assert mutated2 is True
    assert payload2["ok"] is True
    assert payload2["data"]["mandate_count"] >= 1


def test_dispatch_poll_wait_and_cancel(tmp_path: Path):
    runtime = OrchestraRuntime(repo_root=tmp_path, state_root=tmp_path / ".state")
    scheduler = DummyScheduler()
    task = runtime.start_task("Analyze changelog", "standard", "docs")
    runtime.set_mandates(
        task["task_id"],
        [{"musician": "cello", "title": "x", "objective": "y"}],
    )

    dispatched, mutated = _call(
        "dispatch_by_mandate",
        {"task_id": task["task_id"]},
        runtime,
        scheduler,
    )
    assert mutated is True
    assert dispatched["ok"] is True
    assert dispatched["data"]["assignment_ids"] == ["asg_test_1"]

    polled, _ = _call(
        "poll_assignments",
        {"task_id": task["task_id"]},
        runtime,
        scheduler,
    )
    assert polled["ok"] is True
    assert polled["data"]["assignments"][0]["status"] == "completed"

    waited, waited_mutated = _call(
        "wait_assignment",
        {"assignment_id": "asg_test_1"},
        runtime,
        scheduler,
    )
    assert waited_mutated is True
    assert waited["ok"] is True

    runtime.assignments["asg_test_1"] = runtime.create_assignment(
        task_id=task["task_id"],
        musician="cello",
        goal="x",
        scope=[],
        constraints=[],
        timeout_ms=1000,
    )
    cancelled, cancelled_mutated = _call(
        "cancel_assignment",
        {"assignment_id": "asg_test_1"},
        runtime,
        scheduler,
    )
    assert cancelled_mutated is True
    assert cancelled["ok"] is True


def test_unknown_tool_and_invalid_args_return_error(tmp_path: Path):
    runtime = OrchestraRuntime(repo_root=tmp_path, state_root=tmp_path / ".state")
    scheduler = DummyScheduler()

    unknown, mutated = _call("nope", {}, runtime, scheduler)
    assert mutated is False
    assert unknown["ok"] is False

    bad_json_text, bad_mutated = handle_orchestra_tool_call(
        "compose_ensemble",
        "{not-json",
        runtime=runtime,
        scheduler=scheduler,
    )
    bad_json = json.loads(bad_json_text)
    assert bad_mutated is False
    assert bad_json["ok"] is False
