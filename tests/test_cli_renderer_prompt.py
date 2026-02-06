import builtins
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from cli_renderer import CLIRenderer


def test_prompt_follow_up_plain(monkeypatch):
    renderer = CLIRenderer()

    monkeypatch.setattr(builtins, "input", lambda _: "next step")

    assert renderer.prompt_follow_up() == "next step"


def test_prompt_follow_up_vim_command(monkeypatch):
    renderer = CLIRenderer()
    inputs = iter(["v"])  # Should only consume once

    monkeypatch.setattr(builtins, "input", lambda _: next(inputs))

    captured_seed = {}

    def fake_editor(seed_text):
        captured_seed["seed"] = seed_text
        return "Edited prompt"

    monkeypatch.setattr(renderer, "_edit_prompt_via_editor", fake_editor)

    assert renderer.prompt_follow_up() == "Edited prompt"
    assert captured_seed["seed"] == ""


def test_prompt_follow_up_vim_with_initial_text(monkeypatch):
    renderer = CLIRenderer()
    inputs = iter(["   v refine this"])

    monkeypatch.setattr(builtins, "input", lambda _: next(inputs))

    captured = {}

    def fake_editor(seed_text):
        captured["seed"] = seed_text
        return "result"

    monkeypatch.setattr(renderer, "_edit_prompt_via_editor", fake_editor)

    assert renderer.prompt_follow_up() == "result"
    assert captured["seed"] == "refine this"


def test_prompt_follow_up_vim_empty_result(monkeypatch):
    renderer = CLIRenderer()
    inputs = iter(["v", "final instruction"])
    messages = []

    monkeypatch.setattr(builtins, "input", lambda _: next(inputs))

    def fake_editor(_):
        return ""

    monkeypatch.setattr(renderer, "_edit_prompt_via_editor", fake_editor)
    monkeypatch.setattr(renderer, "display_info", messages.append)

    assert renderer.prompt_follow_up() == "final instruction"
    assert any("Prompt cancelled" in msg for msg in messages)


def test_prompt_follow_up_vim_failure(monkeypatch):
    renderer = CLIRenderer()
    inputs = iter(["v", "done"])

    monkeypatch.setattr(builtins, "input", lambda _: next(inputs))

    def fake_editor(_):
        return None

    monkeypatch.setattr(renderer, "_edit_prompt_via_editor", fake_editor)

    assert renderer.prompt_follow_up() == "done"
