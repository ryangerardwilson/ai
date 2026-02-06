from types import SimpleNamespace
from pathlib import Path
import sys

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
