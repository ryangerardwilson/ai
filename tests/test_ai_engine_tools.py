from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_engine_tools
from bash_executor import CommandResult


class DummyRenderer:
    def __init__(self) -> None:
        self.shell_outputs: list[str] = []
        self.errors: list[str] = []
        self.infos: list[str] = []
        self.plan_updates: list[tuple[str, str | None]] = []

    def display_shell_output(self, text: str) -> None:  # type: ignore[override]
        self.shell_outputs.append(text)

    def display_info(self, text: str) -> None:  # type: ignore[override]
        self.infos.append(text)

    def display_error(self, text: str) -> None:  # type: ignore[override]
        self.errors.append(text)

    def display_assistant_message(self, text: str) -> None:  # pragma: no cover
        pass

    def display_user_prompt(self, prompt: str) -> None:  # pragma: no cover
        pass

    def display_reasoning(self, text: str) -> None:  # pragma: no cover
        pass

    def display_plan_update(self, plan: str, explanation: str | None) -> None:  # type: ignore[override]
        self.plan_updates.append((plan, explanation))

    def review_file_update(self, *args, **kwargs):  # pragma: no cover
        return "no_change"

    def prompt_text(self, prompt: str):  # pragma: no cover
        return None

    def prompt_follow_up(self):  # pragma: no cover
        return None

    def prompt_confirm(self, prompt: str, *, default_no: bool = True) -> bool:  # pragma: no cover
        return False

    def start_loader(self):  # pragma: no cover
        return None, None

    def stop_loader(self) -> None:  # pragma: no cover
        pass

    def consume_completion_messages(self) -> list[str]:  # pragma: no cover
        return []

    def start_reasoning(self, reasoning_id: str) -> None:  # pragma: no cover
        pass

    def update_reasoning(self, reasoning_id: str, delta: str) -> None:  # pragma: no cover
        pass

    def finish_reasoning(self, reasoning_id: str, final: str | None = None) -> None:  # pragma: no cover
        pass

    def start_assistant_stream(self, stream_id: str) -> None:  # pragma: no cover
        pass

    def update_assistant_stream(self, stream_id: str, delta: str) -> None:  # pragma: no cover
        pass

    def finish_assistant_stream(
        self, stream_id: str, final_text: str | None = None
    ) -> None:  # pragma: no cover
        pass

    def enable_debug_logging(self, stream):  # pragma: no cover
        pass

    def start_hotkey_listener(self) -> None:  # pragma: no cover
        pass

    def stop_hotkey_listener(self) -> None:  # pragma: no cover
        pass

    def poll_hotkey_event(self):  # pragma: no cover
        return None


def make_runtime(
    renderer: DummyRenderer, *, root: Path | None = None
) -> ai_engine_tools.ToolRuntime:
    repo_root = (root or Path("/repo")).resolve()
    return ai_engine_tools.ToolRuntime(
        renderer=renderer,
        base_root=repo_root,
        default_root=repo_root,
        plan_state={},
        latest_instruction="",
    )


def test_unit_test_coverage_runs_pytest(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run(command_str, *, cwd, scope_root, timeout, max_output_bytes):
        captured.update(
            {
                "command": command_str,
                "cwd": cwd,
                "scope_root": scope_root,
                "timeout": timeout,
                "max_output_bytes": max_output_bytes,
            }
        )
        return SimpleNamespace(exit_code=0)

    monkeypatch.setattr(ai_engine_tools, "run_sandboxed_bash", fake_run)
    monkeypatch.setattr(ai_engine_tools, "format_command_result", lambda _res: "OK")

    renderer = DummyRenderer()
    runtime = make_runtime(renderer)

    output, mutated = ai_engine_tools.run_unit_test_coverage({}, runtime)

    assert mutated is False
    assert captured["command"] == "pytest --cov --cov-report=term-missing"
    assert captured["cwd"] == runtime.default_root
    assert captured["scope_root"] == runtime.base_root
    assert "$ pytest --cov --cov-report=term-missing" in output
    assert "OK" in output
    assert renderer.shell_outputs == [output]


def test_unit_test_coverage_validates_extra_args():
    renderer = DummyRenderer()
    runtime = make_runtime(renderer)

    message, mutated = ai_engine_tools.run_unit_test_coverage(
        {"extraArgs": "--maxfail=1"}, runtime
    )

    assert mutated is False
    assert message == "error: extraArgs must be a list of strings"


def test_glob_search_lists_matches(tmp_path: Path):
    renderer = DummyRenderer()
    root = tmp_path
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("print('hi')")
    (root / "README.md").write_text("readme")

    runtime = make_runtime(renderer, root=root)

    output, mutated = ai_engine_tools.run_glob_search({"pattern": "**/*.py"}, runtime)

    assert mutated is False
    assert "src/main.py" in output
    assert renderer.infos and "src/main.py" in renderer.infos[-1]


def test_glob_search_respects_limit(tmp_path: Path):
    renderer = DummyRenderer()
    root = tmp_path
    for index in range(3):
        (root / f"file{index}.txt").write_text("data")

    runtime = make_runtime(renderer, root=root)

    output, _ = ai_engine_tools.run_glob_search(
        {"pattern": "*.txt", "limit": 1}, runtime
    )

    lines = output.splitlines()
    assert len(lines) == 2


def test_glob_search_rejects_outside_cwd(tmp_path: Path):
    renderer = DummyRenderer()
    runtime = make_runtime(renderer, root=tmp_path)

    outside = tmp_path.parent
    message, mutated = ai_engine_tools.run_glob_search(
        {"pattern": "*", "cwd": str(outside)}, runtime
    )

    assert mutated is False
    assert message.startswith("error: cwd outside project root")


def test_search_content_uses_rg(monkeypatch, tmp_path: Path):
    renderer = DummyRenderer()
    runtime = make_runtime(renderer, root=tmp_path)
    target = tmp_path / "app.py"
    target.write_text("value = 42\n")

    payload = {
        "type": "match",
        "data": {
            "path": {"text": "app.py"},
            "lines": {"text": "value = 42\n"},
            "line_number": 1,
        },
    }

    result = CommandResult(
        command="rg",
        exit_code=0,
        stdout=json.dumps(payload) + "\n",
        stderr="",
        truncated=False,
    )

    monkeypatch.setattr(ai_engine_tools, "run_sandboxed_bash", lambda *a, **k: result)

    output, mutated = ai_engine_tools.run_search_content({"pattern": "value"}, runtime)

    assert mutated is False
    assert "app.py:1" in output
    assert renderer.infos and "app.py:1" in renderer.infos[-1]


def test_search_content_falls_back_without_rg(monkeypatch, tmp_path: Path):
    renderer = DummyRenderer()
    runtime = make_runtime(renderer, root=tmp_path)
    target = tmp_path / "src"
    target.mkdir()
    file_path = target / "module.py"
    file_path.write_text("def call():\n    pass\n")

    def fake_run(*args, **kwargs):
        raise ai_engine_tools.CommandRejected("not allowed")

    monkeypatch.setattr(ai_engine_tools, "run_sandboxed_bash", fake_run)

    output, mutated = ai_engine_tools.run_search_content(
        {"pattern": "def", "include": "**/*.py"}, runtime
    )

    assert mutated is False
    assert "module.py:1" in output
    # final info line should contain match
    assert renderer.infos
    assert any("module.py:1" in info for info in renderer.infos)


def test_search_content_no_matches(monkeypatch, tmp_path: Path):
    renderer = DummyRenderer()
    runtime = make_runtime(renderer, root=tmp_path)
    (tmp_path / "sample.txt").write_text("nothing to see\n")

    result = CommandResult(
        command="rg",
        exit_code=1,
        stdout="",
        stderr="",
        truncated=False,
    )

    monkeypatch.setattr(ai_engine_tools, "run_sandboxed_bash", lambda *a, **k: result)

    message, mutated = ai_engine_tools.run_search_content({"pattern": "missing"}, runtime)

    assert mutated is False
    assert message.startswith("Search pattern 'missing' returned no matches")


def test_plan_update_replace_sets_plan():
    renderer = DummyRenderer()
    runtime = make_runtime(renderer)

    message, mutated = ai_engine_tools.run_plan_update(
        {
            "todos": [
                {
                    "id": "t1",
                    "content": "Set up project",
                    "status": "pending",
                    "priority": "high",
                }
            ],
            "summary": "Initial setup",
        },
        runtime,
    )

    assert mutated is False
    assert "1 task" in message
    assert runtime.plan_state["todos"][0]["id"] == "t1"
    assert renderer.plan_updates
    plan_text, summary = renderer.plan_updates[-1]
    assert "Set up project" in plan_text
    assert summary == "Initial setup"


def test_plan_update_merge_when_replace_false():
    renderer = DummyRenderer()
    runtime = make_runtime(renderer)

    ai_engine_tools.run_plan_update(
        {
            "todos": [
                {"id": "a", "content": "Task A", "status": "pending"},
                {"id": "b", "content": "Task B", "status": "pending"},
            ]
        },
        runtime,
    )

    message, _ = ai_engine_tools.run_plan_update(
        {
            "todos": [
                {"id": "b", "content": "Task B updated", "status": "in_progress"},
                {"id": "c", "content": "Task C", "status": "pending"},
            ],
            "replace": False,
        },
        runtime,
    )

    todos = runtime.plan_state["todos"]
    assert [todo["id"] for todo in todos] == ["a", "b", "c"]
    assert todos[1]["status"] == "in_progress"
    assert "3 tasks" in message


def test_plan_update_validates_status():
    renderer = DummyRenderer()
    runtime = make_runtime(renderer)

    message, mutated = ai_engine_tools.run_plan_update(
        {
            "todos": [
                {"id": "oops", "content": "Bad", "status": "done"},
            ]
        },
        runtime,
    )

    assert mutated is False
    assert message.startswith("error: todo 'oops' has invalid status")
