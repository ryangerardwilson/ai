from collections import deque
from pathlib import Path
from typing import Any

import orchestra_mode


class DummyRenderer:
    def __init__(self):
        self.prompts = deque(["audit README", None])
        self.infos = []
        self.errors = []
        self.user_prompts = []

    def prompt_follow_up(self):
        return self.prompts.popleft()

    def display_info(self, text):
        self.infos.append(text)

    def display_error(self, text):
        self.errors.append(text)

    def display_user_prompt(self, text):
        self.user_prompts.append(text)


def test_orchestra_mode_resets_and_requires_fresh_ensemble(monkeypatch, tmp_path: Path):
    class FakeRuntime:
        def __init__(self, repo_root):
            self.repo_root = repo_root
            self.run_id = "run123"

    class FakeTmux:
        def __init__(self, *, session_name, repo_root):
            self.session_name = session_name
            self.repo_root = repo_root

        def ensure_session(self):
            return None

        def focus_orchestrator_pane(self):
            return None

        def uses_current_session(self):
            return True

    class FakeScheduler:
        def __init__(self, runtime, tmux):
            self.runtime = runtime
            self.tmux = tmux
            self.reset_calls = 0

        def reset_for_new_task(self):
            self.reset_calls += 1
            return {"closed_panes": 0, "cancelled_assignments": 0}

    captured = {"instructions": [], "scheduler": None}

    class FakeEngine:
        def __init__(self, **kwargs):
            captured["scheduler"] = kwargs["orchestra_scheduler"]

        def run_conversation(self, prompt, scope, *, display_prompt=True):
            captured["instructions"].append(prompt)
            return 0

    monkeypatch.setattr(orchestra_mode, "OrchestraRuntime", FakeRuntime)
    monkeypatch.setattr(orchestra_mode, "TmuxManager", FakeTmux)
    monkeypatch.setattr(orchestra_mode, "OrchestraScheduler", FakeScheduler)
    monkeypatch.setattr(orchestra_mode, "AIEngine", FakeEngine)

    renderer = DummyRenderer()
    rc = orchestra_mode.run_orchestra_mode(
        renderer=renderer,
        config={"openai_api_key": "sk-1"},
        default_model="gpt-5-codex",
        repo_root=tmp_path,
    )

    assert rc == 0
    assert renderer.user_prompts == ["audit README"]
    assert captured["scheduler"].reset_calls == 1
    assert captured["instructions"]
    assert "must spawn a fresh musician ensemble" in captured["instructions"][0]
    assert captured["instructions"][0].endswith("audit README")


def test_orchestra_mode_skips_reset_when_discussing_agents(monkeypatch, tmp_path: Path):
    class PlanningRenderer(DummyRenderer):
        def __init__(self):
            self.prompts = deque(["which agents should we spawn for this task?", None])
            self.infos = []
            self.errors = []
            self.user_prompts = []

    class FakeRuntime:
        def __init__(self, repo_root):
            self.repo_root = repo_root
            self.run_id = "run456"

    class FakeTmux:
        def __init__(self, *, session_name, repo_root):
            self.session_name = session_name
            self.repo_root = repo_root

        def ensure_session(self):
            return None

        def focus_orchestrator_pane(self):
            return None

        def uses_current_session(self):
            return True

    class FakeScheduler:
        def __init__(self, runtime, tmux):
            self.reset_calls = 0

        def reset_for_new_task(self):
            self.reset_calls += 1
            return {"closed_panes": 0, "cancelled_assignments": 0}

    captured = {"instructions": [], "scheduler": None}

    class FakeEngine:
        def __init__(self, **kwargs):
            captured["scheduler"] = kwargs["orchestra_scheduler"]

        def run_conversation(self, prompt, scope, *, display_prompt=True):
            captured["instructions"].append(prompt)
            return 0

    monkeypatch.setattr(orchestra_mode, "OrchestraRuntime", FakeRuntime)
    monkeypatch.setattr(orchestra_mode, "TmuxManager", FakeTmux)
    monkeypatch.setattr(orchestra_mode, "OrchestraScheduler", FakeScheduler)
    monkeypatch.setattr(orchestra_mode, "AIEngine", FakeEngine)

    renderer = PlanningRenderer()
    rc = orchestra_mode.run_orchestra_mode(
        renderer=renderer,
        config={"openai_api_key": "sk-1"},
        default_model="gpt-5-codex",
        repo_root=tmp_path,
    )

    assert rc == 0
    assert captured["scheduler"].reset_calls == 0
    assert "do not dispatch musicians unless explicitly asked" in captured["instructions"][0]


def test_orchestra_mode_ctrl_c_closes_excess_panes(monkeypatch, tmp_path: Path):
    class InterruptingRenderer(DummyRenderer):
        def __init__(self):
            self.infos = []
            self.errors = []
            self.user_prompts = []

        def prompt_follow_up(self):
            raise KeyboardInterrupt

    class FakeRuntime:
        def __init__(self, repo_root):
            self.repo_root = repo_root
            self.run_id = "run789"
            self.cleaned = False

        def cleanup(self):
            self.cleaned = True

    class FakeTmux:
        def __init__(self, *, session_name, repo_root):
            self.closed = 0

        def ensure_session(self):
            return None

        def focus_orchestrator_pane(self):
            return None

        def uses_current_session(self):
            return True

        def close_excess_panes(self):
            self.closed += 1
            return 2

    class FakeScheduler:
        def __init__(self, runtime, tmux):
            self.runtime = runtime
            self.tmux = tmux

    class FakeEngine:
        def __init__(self, **kwargs):
            return None

    holder: dict[str, Any] = {"runtime": None, "tmux": None}

    def runtime_factory(repo_root):
        inst = FakeRuntime(repo_root)
        holder["runtime"] = inst
        return inst

    def tmux_factory(*, session_name, repo_root):
        inst = FakeTmux(session_name=session_name, repo_root=repo_root)
        holder["tmux"] = inst
        return inst

    monkeypatch.setattr(orchestra_mode, "OrchestraRuntime", runtime_factory)
    monkeypatch.setattr(orchestra_mode, "TmuxManager", tmux_factory)
    monkeypatch.setattr(orchestra_mode, "OrchestraScheduler", FakeScheduler)
    monkeypatch.setattr(orchestra_mode, "AIEngine", FakeEngine)

    renderer = InterruptingRenderer()
    rc = orchestra_mode.run_orchestra_mode(
        renderer=renderer,
        config={"openai_api_key": "sk-1"},
        default_model="gpt-5-codex",
        repo_root=tmp_path,
    )

    assert rc == 130
    assert any("Interrupted by user." in msg for msg in renderer.infos)
    assert holder["tmux"].closed == 1
    assert holder["runtime"].cleaned is True
