from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

import openai

from ai_engine_config import build_engine_settings, resolve_model
from ai_engine_tools import READONLY_TOOL_DEFINITIONS, ToolRuntime, handle_tool_call
from contextualizer import (
    DEFAULT_READ_LIMIT,
    MAX_READ_BYTES,
    collect_context,
    format_context_for_prompt,
    format_file_slice_for_prompt,
    read_file_slice,
)


class InlineModeRenderer:
    def __init__(
        self,
        *,
        renderer: Any,
        config: Dict[str, Any],
        default_model: str = "gpt-5-codex",
    ) -> None:
        self.renderer = renderer
        self.config = config
        settings = build_engine_settings(config, default_model)
        self.default_model = settings.default_model
        self._api_key = settings.api_key
        self.client = openai.OpenAI(api_key=self._api_key)
        self._debug_api = settings.debug_api
        self._debug_stream: TextIO = sys.stderr

    def _api_debug(self, message: str) -> None:
        if self._debug_api:
            print(f"[openai-debug] {message}", file=self._debug_stream)

    def run(self, *, prompt: str, scopes: List[Path]) -> int:
        raw_prompt = (prompt or "").strip()
        if not raw_prompt:
            self.renderer.display_error("Inline prompt cannot be empty.")
            return 1

        self.renderer.display_user_prompt(raw_prompt)

        repo_root = Path.cwd().resolve()
        context_settings = self.config.get("context_settings", {})
        context_max_bytes = int(context_settings.get("max_bytes", MAX_READ_BYTES))
        context_default_limit = int(
            context_settings.get("read_limit", DEFAULT_READ_LIMIT)
        )

        try:
            prompt_context = self._build_context(
                repo_root,
                scopes,
                max_bytes=context_max_bytes,
                default_limit=context_default_limit,
            )
        except ValueError as exc:
            self.renderer.display_error(str(exc))
            return 1

        model_id = resolve_model(
            "inline", self.config, default_model=self.default_model
        )

        system_prompt = (
            "You are Codex CLI inline mode. Provide a single, self-contained answer. "
            "You may use read-only tools (read_file, glob, search_content) to inspect the repository. "
            "Do not ask follow-up questions, do not claim to have edited files or run shell commands, "
            "and do not output patch or write instructions as if they were applied."
        )

        user_message = "\n".join(
            [
                "Repository snapshot:",
                prompt_context or "(no context collected)",
                "",
                "Task:",
                raw_prompt,
                "",
                "Inline mode: read-only; answer once and exit.",
            ]
        )

        conversation_items: List[Dict[str, Any]] = [
            self._make_user_message(user_message)
        ]

        runtime = ToolRuntime(
            renderer=self.renderer,
            base_root=repo_root,
            default_root=repo_root,
            plan_state={},
            latest_instruction=raw_prompt,
            jfdi_enabled=False,
            seen_writes=set(),
            debug=self._api_debug,
        )

        max_tool_rounds = 6
        for _ in range(max_tool_rounds):
            response = self._create_response(
                model_id=model_id,
                system_prompt=system_prompt,
                conversation_items=conversation_items,
            )
            if response is None:
                return 1

            tool_calls = 0
            assistant_messages: List[str] = []

            for item in getattr(response, "output", []) or []:
                item_type = getattr(item, "type", "")

                if item_type == "message":
                    text = self._extract_message_text(item)
                    if text:
                        assistant_messages.append(text)
                        conversation_items.append(self._make_assistant_message(text))
                elif item_type in {"tool_call", "function_call"}:
                    item_payload = self._convert_response_item(item)
                    tool_name = item_payload.get("name") or getattr(item, "name", "")
                    raw_item_id = getattr(item, "id", None)
                    raw_call_id = getattr(item, "call_id", None) or raw_item_id
                    call_id = str(raw_call_id or f"tool-{tool_name}")
                    arguments_payload = item_payload.get("arguments", {})
                    conversation_items.append(
                        self._make_tool_call_item(
                            call_id=call_id,
                            tool_name=tool_name,
                            arguments=arguments_payload,
                            raw_id=raw_item_id,
                        )
                    )
                    result_text, _ = handle_tool_call(
                        tool_name, arguments_payload, runtime
                    )
                    conversation_items.append(
                        self._make_tool_result_message(call_id, result_text)
                    )
                    tool_calls += 1

            if tool_calls:
                continue

            if assistant_messages:
                self.renderer.display_assistant_message(assistant_messages[-1])
                return 0

            self.renderer.display_error("Model returned no content.")
            return 1

        self.renderer.display_error("Inline mode exceeded tool call limit.")
        return 1

    def _create_response(
        self,
        *,
        model_id: str,
        system_prompt: str,
        conversation_items: List[Dict[str, Any]],
    ) -> Optional[Any]:
        self.renderer.start_loader()
        try:
            self._api_debug(
                "inline request model=%s items=%d"
                % (model_id, len(conversation_items))
            )
            response = self.client.responses.create(
                model=model_id,
                instructions=system_prompt,
                input=conversation_items,
                tools=READONLY_TOOL_DEFINITIONS,
                tool_choice="auto",
            )
            self._api_debug(
                "inline response status=%s"
                % (getattr(response, "status", None))
            )
            return response
        except Exception as exc:
            self.renderer.display_error(f"Error: {exc}")
            return None
        finally:
            self.renderer.stop_loader()

    def _build_context(
        self,
        repo_root: Path,
        scopes: List[Path],
        *,
        max_bytes: int,
        default_limit: int,
    ) -> str:
        if not scopes:
            collected = collect_context(
                repo_root,
                limit_bytes=max_bytes,
                default_limit=default_limit,
                include_listing=False,
            )
            return format_context_for_prompt(collected)

        sections: List[str] = []
        for scope in scopes:
            resolved = scope.resolve()
            try:
                relative = resolved.relative_to(repo_root)
            except ValueError as exc:
                raise ValueError("Inline scope must be inside the repository.") from exc

            if not resolved.exists():
                raise ValueError(f"Inline scope not found: {resolved}")

            label = str(relative) or "."
            sections.append(f"## Scope: {label}")

            if resolved.is_dir():
                collected = collect_context(
                    resolved,
                    limit_bytes=max_bytes,
                    default_limit=default_limit,
                    include_listing=True,
                )
                sections.append(format_context_for_prompt(collected))
            else:
                file_slice = read_file_slice(
                    resolved, offset=0, limit=default_limit, max_bytes=max_bytes
                )
                sections.append(
                    format_file_slice_for_prompt(file_slice, rel_root=repo_root)
                )

        return "\n\n".join(section for section in sections if section)

    @staticmethod
    def _extract_message_text(item: Any) -> str:
        text_parts: List[str] = []
        for block in getattr(item, "content", []) or []:
            if getattr(block, "type", "").endswith("text"):
                text_parts.append(getattr(block, "text", ""))
        return "".join(text_parts).strip()

    def _convert_response_item(self, obj: Any) -> Dict[str, Any]:
        data = self._to_plain_data(obj)
        if isinstance(data, dict):
            return data
        raise TypeError(
            f"Unable to convert response item of type {type(obj)!r} to dict"
        )

    def _to_plain_data(self, obj: Any) -> Any:
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        if isinstance(obj, dict):
            return {key: self._to_plain_data(value) for key, value in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [self._to_plain_data(value) for value in obj]
        if hasattr(obj, "model_dump"):
            return self._to_plain_data(obj.model_dump())
        if hasattr(obj, "dict"):
            return self._to_plain_data(obj.dict())
        try:
            iterable = iter(obj)  # type: ignore[arg-type]
        except TypeError:
            return str(obj)
        else:
            return [self._to_plain_data(item) for item in iterable]

    @staticmethod
    def _make_user_message(text: str) -> Dict[str, Any]:
        return {"role": "user", "content": [{"type": "input_text", "text": text}]}

    @staticmethod
    def _make_assistant_message(text: str) -> Dict[str, Any]:
        return {
            "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
        }

    @staticmethod
    def _make_tool_result_message(call_id: str, text: str) -> Dict[str, Any]:
        return {
            "type": "function_call_output",
            "call_id": call_id,
            "output": text,
        }

    @staticmethod
    def _make_tool_call_item(
        *,
        call_id: str,
        tool_name: str,
        arguments: Any,
        raw_id: Any = None,
    ) -> Dict[str, Any]:
        serialized_arguments = (
            arguments if isinstance(arguments, str) else json.dumps(arguments or {})
        )
        item: Dict[str, Any] = {
            "type": "function_call",
            "call_id": call_id,
            "name": tool_name,
            "arguments": serialized_arguments,
        }
        if raw_id is not None:
            item["id"] = str(raw_id)
        return item


__all__ = ["InlineModeRenderer"]
