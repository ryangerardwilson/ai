"""Prototype script to inspect reasoning stream events from the Responses API.

Run with:

    OPENAI_API_KEY=... python prototype_reasoning.py

Optionally override the model or reasoning effort:

    AI_MODEL=gpt-5 AI_REASONING_EFFORT=high python prototype_reasoning.py

This will print each streamed event, highlighting reasoning deltas and output
text as they arrive.
"""

from __future__ import annotations

import os
import sys
from typing import Any, cast

from openai import OpenAI


def main() -> int:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is required", file=sys.stderr)
        return 1

    model = os.environ.get("AI_MODEL", "gpt-5")
    reasoning_effort = os.environ.get("AI_REASONING_EFFORT", "medium")

    client = OpenAI(api_key=api_key)

    prompt = (
        "You are an expert mathematician. Explain step by step how to prove that "
        "the square root of 2 is irrational. Present each logical step clearly."
    )

    print(f"Model: {model}")
    print(f"Reasoning effort: {reasoning_effort}")
    print("--- streaming events ---")

    try:
        with client.responses.stream(
            model=model,
            input=[{"role": "user", "content": prompt}],
            reasoning=cast(Any, {"effort": reasoning_effort, "summary": "auto"}),
        ) as stream:
            for event in stream:
                handle_event(event)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:  # pragma: no cover - prototype script
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


def handle_event(event: Any) -> None:
    event_type = getattr(event, "type", "unknown")

    if event_type in {
        "response.reasoning_text.delta",
        "response.reasoning_summary_text.delta",
    }:
        delta = getattr(event, "delta", "")
        item_id = getattr(event, "item_id", "?")
        print(f"[reasoning delta] item={item_id} -> {delta!r}")
        return

    if event_type in {
        "response.reasoning_text.done",
        "response.reasoning_summary_text.done",
    }:
        text = getattr(event, "text", "")
        item_id = getattr(event, "item_id", "?")
        print(f"[reasoning done] item={item_id} -> {text!r}")
        return

    if event_type == "response.output_text.delta":
        delta = getattr(event, "delta", "")
        print(f"[output delta] {delta!r}")
        return

    if event_type == "response.output_text.done":
        text = getattr(event, "text", "")
        print(f"[output done] {text!r}")
        return

    if event_type == "response.completed":
        print("[completed]")
        return

    if event_type == "response.error":
        error = getattr(event, "error", None)
        print(f"[error] {error}")
        return

    # fallback for other events
    print(f"[{event_type}] {event}")


if __name__ == "__main__":
    sys.exit(main())
