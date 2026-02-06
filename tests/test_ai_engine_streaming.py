from collections import deque
from types import SimpleNamespace
from pathlib import Path
import sys


def test_run_conversation_ctrl_q_cancels(monkeypatch):
    final_response = SimpleNamespace(output=[])

    base_events = [
        SimpleNamespace(
            type="response.output_text.delta",
            delta="Partial",
            item_id="msg_1",
            content_index=0,
            output_index=0,
        ),
    ]

    cancel_emitted = False

    class EventIterable:
        def __iter__(self_nonlocal):
            nonlocal cancel_emitted
            for event in base_events:
                if not cancel_emitted:
                    renderer.emit_hotkey("quit")
                    cancel_emitted = True
                yield event

    renderer = DummyRenderer()

    dummy_client = DummyClient(lambda: DummyStream(EventIterable(), final_response))
    monkeypatch.setattr(ai_engine.openai, "OpenAI", lambda **kwargs: dummy_client)

    engine = ai_engine.AIEngine(renderer=renderer, config={"openai_api_key": "sk-1"})

    rc = engine.run_conversation("What?", None)

    assert rc == 0
    assert any("Prompt cancelled" in msg for msg in renderer.infos)
    assert renderer.assistant_messages == []


def test_run_conversation_ctrl_r_retries(monkeypatch):
    final_response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                id="msg_1",
                content=[SimpleNamespace(type="output_text", text="Retried result")],
            )
        ]
    )

    first_events = [
        SimpleNamespace(
            type="response.output_text.delta",
            delta="Partial",
            item_id="msg_1",
            content_index=0,
            output_index=0,
        ),
    ]
    second_events = [
        SimpleNamespace(
            type="response.output_text.delta",
            delta="Retried result",
            item_id="msg_1",
            content_index=0,
            output_index=0,
        ),
        SimpleNamespace(
            type="response.output_text.done",
            text="Retried result",
            item_id="msg_1",
            content_index=0,
            output_index=0,
        ),
        SimpleNamespace(type="response.completed", response=final_response),
    ]

    renderer = DummyRenderer()

    stream_calls = {"count": 0}

    def stream_factory():
        stream_calls["count"] += 1
        if stream_calls["count"] == 1:

            class FirstIterable:
                def __iter__(self_nonlocal):
                    renderer.emit_hotkey("retry")
                    for event in first_events:
                        yield event

            return DummyStream(FirstIterable(), SimpleNamespace(output=[]))
        return DummyStream(second_events, final_response)

    dummy_client = DummyClient(stream_factory)
    monkeypatch.setattr(ai_engine.openai, "OpenAI", lambda **kwargs: dummy_client)

    engine = ai_engine.AIEngine(renderer=renderer, config={"openai_api_key": "sk-1"})

    rc = engine.run_conversation("Retry?", None)

    assert rc == 0
    assert stream_calls["count"] == 2
    assert renderer.assistant_stream_final == "Retried result"
    assert any("Retrying prompt" in msg for msg in renderer.infos)


import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_engine


class DummyRenderer:
    def __init__(self):
        self.user_prompts: list[str] = []
        self.assistant_messages: list[str] = []
        self.infos: list[str] = []
        self.errors: list[str] = []
        self.reasoning_updates: list[str] = []
        self.reasoning_final: str | None = None
        self.reasoning_started = False
        self.assistant_stream_started = False
        self.assistant_stream_chunks: list[str] = []
        self.assistant_stream_final: str | None = None
        self.hotkey_events = deque()

    def display_info(self, text: str) -> None:
        self.infos.append(text)

    def display_error(self, text: str) -> None:
        self.errors.append(text)

    def display_assistant_message(self, text: str) -> None:
        self.assistant_messages.append(text)

    def display_user_prompt(self, prompt: str) -> None:
        self.user_prompts.append(prompt)

    def display_reasoning(self, text: str) -> None:
        pass

    def display_shell_output(self, text: str) -> None:
        pass

    def display_plan_update(self, plan: str, explanation: str | None) -> None:
        pass

    def review_file_update(self, *args, **kwargs):
        return "no_change"

    def prompt_text(self, prompt: str):
        return None

    def prompt_follow_up(self):
        return None

    def prompt_confirm(self, prompt: str, *, default_no: bool = True) -> bool:
        return False

    def start_loader(self):
        return None, None

    def stop_loader(self) -> None:
        pass

    def consume_completion_messages(self) -> list[str]:
        return []

    def start_reasoning(self, reasoning_id: str) -> None:
        self.reasoning_started = True

    def update_reasoning(self, reasoning_id: str, delta: str) -> None:
        self.reasoning_updates.append(delta)

    def finish_reasoning(self, reasoning_id: str, final: str | None = None) -> None:
        self.reasoning_final = final

    def start_assistant_stream(self, stream_id: str) -> None:
        self.assistant_stream_started = True

    def update_assistant_stream(self, stream_id: str, delta: str) -> None:
        self.assistant_stream_chunks.append(delta)

    def finish_assistant_stream(
        self, stream_id: str, final_text: str | None = None
    ) -> None:
        self.assistant_stream_final = final_text

    def start_hotkey_listener(self) -> None:
        pass

    def stop_hotkey_listener(self) -> None:
        pass

    def poll_hotkey_event(self):
        try:
            return self.hotkey_events.popleft()
        except IndexError:
            return None

    def emit_hotkey(self, name: str) -> None:
        self.hotkey_events.append(name)

    def enable_debug_logging(self, stream):
        pass


class DummyStream:
    def __init__(self, events, final_response):
        self._events = events
        self.response = final_response
        self.final_response = final_response

    def __iter__(self):
        return iter(self._events)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyResponses:
    def __init__(self, stream_factory):
        self._stream_factory = stream_factory

    def stream(self, **_kwargs):
        return self._stream_factory()


class DummyClient:
    def __init__(self, stream_factory):
        self.responses = DummyResponses(stream_factory)


@pytest.fixture(autouse=True)
def patch_context(monkeypatch):
    monkeypatch.setattr(ai_engine, "collect_context", lambda *args, **kwargs: object())
    monkeypatch.setattr(ai_engine, "format_context_for_prompt", lambda *_: "context")


def test_run_conversation_streams_reasoning(monkeypatch):
    final_response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                id="msg_1",
                content=[SimpleNamespace(type="output_text", text="Result text")],
            )
        ]
    )

    events = [
        SimpleNamespace(
            type="response.reasoning_text.delta",
            delta="thinking",
            item_id="item-1",
            content_index=0,
            output_index=0,
        ),
        SimpleNamespace(
            type="response.reasoning_text.done",
            text="thinking",
            item_id="item-1",
            content_index=0,
            output_index=0,
        ),
        SimpleNamespace(
            type="response.output_text.delta",
            delta="Result ",
            item_id="msg_1",
            content_index=0,
            output_index=0,
        ),
        SimpleNamespace(
            type="response.output_text.delta",
            delta="text",
            item_id="msg_1",
            content_index=0,
            output_index=0,
        ),
        SimpleNamespace(
            type="response.output_text.done",
            text="Result text",
            item_id="msg_1",
            content_index=0,
            output_index=0,
        ),
        SimpleNamespace(type="response.completed", response=final_response),
    ]

    dummy_client = DummyClient(lambda: DummyStream(events, final_response))
    monkeypatch.setattr(ai_engine.openai, "OpenAI", lambda **kwargs: dummy_client)

    renderer = DummyRenderer()
    engine = ai_engine.AIEngine(renderer=renderer, config={"openai_api_key": "sk-1"})

    rc = engine.run_conversation("What?", None)

    assert rc == 0
    assert renderer.user_prompts == ["What?"]
    assert renderer.reasoning_started is True
    assert renderer.reasoning_updates == ["thinking"]
    assert renderer.reasoning_final == "thinking"
    assert renderer.assistant_stream_started is True
    assert renderer.assistant_stream_chunks == ["Result ", "text"]
    assert renderer.assistant_stream_final == "Result text"
