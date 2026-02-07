from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import ai_engine_tools


class DummyRenderer:
    def __init__(self) -> None:
        self.shell_outputs: list[str] = []
        self.errors: list[str] = []

    def display_shell_output(self, text: str) -> None:  # type: ignore[override]
        self.shell_outputs.append(text)

    def display_info(self, text: str) -> None:  # pragma: no cover
        pass

    def display_error(self, text: str) -> None:  # type: ignore[override]
        self.errors.append(text)

    def display_assistant_message(self, text: str) -> None:  # pragma: no cover
        pass

    def display_user_prompt(self, prompt: str) -> None:  # pragma: no cover
        pass

    def display_reasoning(self, text: str) -> None:  # pragma: no cover
        pass

    def display_plan_update(self, plan: str, explanation: str | None) -> None:  # pragma: no cover
        pass

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


def make_runtime(renderer: DummyRenderer) -> ai_engine_tools.ToolRuntime:
    repo_root = Path("/repo")
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
