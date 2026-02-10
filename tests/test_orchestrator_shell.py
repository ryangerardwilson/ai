from pathlib import Path

import pytest

import orchestrator
from bash_executor import CommandResult


class DummyRenderer:
    def __init__(self, *, prompt_inputs=None, follow_ups=None):
        self._prompt_inputs = iter(prompt_inputs or [])
        self._follow_ups = iter(follow_ups or [])
        self.infos = []
        self.errors = []
        self.shell_outputs = []
        self.user_prompts = []
        self.last_prompt = None
        self.consumed_completion_messages = []

    # Interface --------------------------------------------------------
    def display_info(self, text):
        if text:
            self.infos.append(text)

    def display_error(self, text):
        if text:
            self.errors.append(text)

    def display_shell_output(self, text):
        if text is not None:
            self.shell_outputs.append(text)

    def display_user_prompt(self, prompt):
        self.user_prompts.append(prompt)

    def prompt_text(self, prompt):
        self.last_prompt = prompt
        try:
            return next(self._prompt_inputs)
        except StopIteration:
            return ""

    def prompt_follow_up(self):
        try:
            return next(self._follow_ups)
        except StopIteration:
            return None

    def consume_completion_messages(self):  # pragma: no cover - not used
        return list(self.consumed_completion_messages)

    # Unused but required API (no-op stubs) ----------------------------
    def enable_debug_logging(self, _stream):  # pragma: no cover
        return None

    def edit_prompt(self):  # pragma: no cover
        return None

    def start_hotkey_listener(self):  # pragma: no cover
        return None

    def stop_hotkey_listener(self):  # pragma: no cover
        return None


class DummyEngine:
    def __init__(self, *, renderer, config, default_model):
        self.renderer = renderer
        self.config = config
        self.default_model = default_model
        self.last_conversation = None

    def enable_api_debug(self, _stream):  # pragma: no cover
        return None

    def run_conversation(self, prompt, scope, *, display_prompt=True):
        self.last_conversation = (prompt, scope, display_prompt)
        return 0

    def run_edit(self, *_args, **_kwargs):  # pragma: no cover
        return 0


@pytest.fixture
def orchestrator_factory(monkeypatch, tmp_path):
    def _build(*, prompt_inputs=None, follow_ups=None):
        renderer_box = {}

        monkeypatch.setattr(
            orchestrator,
            "load_config",
            lambda: {
                "openai_api_key": "test-key",
                "model": "test-model",
                "dog_whistle": "jfdi",
            },
        )
        monkeypatch.setattr(
            orchestrator, "get_config_path", lambda: tmp_path / "config.json"
        )
        monkeypatch.setattr(
            orchestrator.Orchestrator, "_bootstrap_config", lambda self: None
        )

        def build_renderer(*_args, **_kwargs):
            renderer = DummyRenderer(prompt_inputs=prompt_inputs, follow_ups=follow_ups)
            renderer_box["instance"] = renderer
            return renderer

        monkeypatch.setattr(orchestrator, "CLIRenderer", build_renderer)
        monkeypatch.setattr(orchestrator, "AIEngine", DummyEngine)

        inst = orchestrator.Orchestrator()
        renderer = renderer_box["instance"]
        engine = inst.engine
        return inst, renderer, engine

    return _build


def test_run_shell_command_executes_immediately(
    monkeypatch, orchestrator_factory, tmp_path
):
    orch, renderer, _ = orchestrator_factory()

    capture = {}

    def fake_run(command, cwd, scope_root, timeout, max_output_bytes):
        capture.update(
            {
                "command": command,
                "cwd": cwd,
                "scope_root": scope_root,
                "timeout": timeout,
                "max_output_bytes": max_output_bytes,
            }
        )
        return CommandResult(
            command=command,
            exit_code=0,
            stdout="ok\n",
            stderr="",
            truncated=False,
        )

    monkeypatch.setattr(orchestrator, "run_sandboxed_bash", fake_run)

    scope_dir = tmp_path / "project"
    scope_dir.mkdir()

    rc = orch.run([str(scope_dir), "!echo", "hello", "world"])

    assert rc == 0
    assert capture["command"] == "echo hello world"
    assert capture["cwd"] == scope_dir.resolve()
    assert capture["scope_root"] == Path.cwd().resolve()
    assert renderer.shell_outputs and renderer.shell_outputs[0].startswith(
        "stdout:\nok"
    )
    assert renderer.user_prompts[0] == "!echo hello world"

    rc_again = orch.run(["!pwd"])
    assert rc_again == 0
    assert renderer.user_prompts[-1] == "!pwd"


def test_interactive_flow_without_args(monkeypatch, orchestrator_factory):
    orch, renderer, engine = orchestrator_factory(
        follow_ups=["review README for typos"]
    )

    result = orch.run([])

    assert result == 0
    assert renderer.user_prompts == ["review README for typos"]
    assert engine.last_conversation == ("review README for typos", None, False)


def test_inline_prompt_arguments_rejected(orchestrator_factory):
    orch, renderer, _ = orchestrator_factory()

    rc = orch.run(["how", "are", "you?"])

    assert rc == 1
    assert any(
        "Inline prompts are no longer supported" in msg for msg in renderer.errors
    )
