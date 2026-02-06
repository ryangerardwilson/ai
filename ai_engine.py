from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, TextIO, cast

import openai

from contextualizer import (
    collect_context,
    format_context_for_prompt,
    DEFAULT_READ_LIMIT,
    MAX_READ_BYTES,
)
from bash_executor import CommandRejected, format_command_result, run_sandboxed_bash


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "read_file",
        "description": "Read a text file from the repository.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Optional byte offset",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional byte limit",
                },
            },
            "required": ["path"],
        },
    },
    {
        "type": "function",
        "name": "write",
        "description": "Write new contents to a file. Accepts absolute or repository-relative paths.",
        "parameters": {
            "type": "object",
            "properties": {
                "filePath": {
                    "type": "string",
                    "description": "Absolute path to the file (or a path relative to the project root)",
                },
                "content": {
                    "type": "string",
                    "description": "Full replacement file contents",
                },
            },
            "required": ["filePath", "content"],
        },
    },
    {
        "type": "function",
        "name": "write_file",
        "description": "Write new contents to a file, replacing the existing text.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
                "contents": {
                    "type": "string",
                    "description": "Full replacement file contents",
                },
            },
            "required": ["path", "contents"],
        },
    },
    {
        "type": "function",
        "name": "apply_patch",
        "description": "Apply a unified diff patch to files (prefer write/write_file when possible).",
        "parameters": {
            "type": "object",
            "properties": {
                "patch": {"type": "string", "description": "Unified diff patch"},
            },
            "required": ["patch"],
        },
    },
    {
        "type": "function",
        "name": "shell",
        "description": "Run a sandboxed shell command within the project scope.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": ["array", "string"],
                    "description": "Command to execute (string or list of strings)",
                    "items": {"type": "string"},
                },
                "workdir": {
                    "type": "string",
                    "description": "Optional working directory",
                },
                "timeout_ms": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional timeout in milliseconds",
                },
            },
            "required": ["command"],
        },
    },
    {
        "type": "function",
        "name": "update_plan",
        "description": "Update the running task plan that the assistant is following.",
        "parameters": {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "New plan outline"},
                "explanation": {
                    "type": "string",
                    "description": "Optional reasoning or notes",
                },
            },
            "required": ["plan"],
        },
    },
]


class RendererProtocol(Protocol):
    def display_info(self, text: str) -> None: ...

    def display_error(self, text: str) -> None: ...

    def display_assistant_message(self, text: str) -> None: ...

    def display_user_prompt(self, prompt: str) -> None: ...

    def display_reasoning(self, text: str) -> None: ...

    def display_shell_output(self, text: str) -> None: ...

    def display_plan_update(self, plan: str, explanation: Optional[str]) -> None: ...

    def review_file_update(
        self,
        target_path: Path,
        display_path: Path,
        old_text: str,
        new_text: str,
        *,
        auto_apply: bool = False,
    ) -> str: ...

    def prompt_text(self, prompt: str) -> Optional[str]: ...

    def prompt_follow_up(self) -> Optional[str]: ...

    def prompt_confirm(self, prompt: str, *, default_no: bool = True) -> bool: ...

    def start_loader(self) -> tuple[Optional[object], Optional[object]]: ...

    def stop_loader(self) -> None: ...

    def consume_completion_messages(self) -> list[str]: ...

    def start_reasoning(self, reasoning_id: str) -> None: ...

    def update_reasoning(self, reasoning_id: str, delta: str) -> None: ...

    def finish_reasoning(self, reasoning_id: str, final: Optional[str] = None) -> None: ...

    def start_assistant_stream(self, stream_id: str) -> None: ...

    def update_assistant_stream(self, stream_id: str, delta: str) -> None: ...

    def finish_assistant_stream(self, stream_id: str, final_text: Optional[str] = None) -> None: ...

    def enable_debug_logging(self, stream: TextIO) -> None: ...


def resolve_api_key(
    candidate: str | None = None, config: Optional[Dict[str, Any]] = None
) -> str:
    if candidate:
        return candidate
    if config:
        api_key = config.get("openai_api_key")
        if api_key:
            return str(api_key)
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        return api_key
    raise RuntimeError("OpenAI API key not configured")


def resolve_model(
    mode: str,
    config: Optional[Dict[str, Any]] = None,
    override: Optional[str] = None,
    default_model: str = "gpt-5-codex",
) -> str:
    if override:
        return override
    cfg = config or {}
    candidate = cfg.get("model")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return default_model


class AIEngine:
    def __init__(
        self,
        *,
        renderer: RendererProtocol,
        config: Dict[str, Any],
        default_model: str = "gpt-5-codex",
    ) -> None:
        self.renderer = renderer
        self.config = config
        self.default_model = default_model
        self._api_key = resolve_api_key(config=config)
        self.client = openai.OpenAI(api_key=self._api_key)
        env_toggle = os.environ.get("AI_SHOW_REASONING")
        if env_toggle is None:
            env_toggle = os.environ.get("AI_SHOW_THINKING")
        config_value = config.get("show_reasoning")
        if config_value is None:
            config_value = config.get("show_thinking", True)
        if env_toggle is not None:
            self.show_reasoning = env_toggle.lower() not in {"0", "false", "no"}
        else:
            self.show_reasoning = bool(config_value)
        env_effort = os.environ.get("AI_REASONING_EFFORT")
        config_effort = self.config.get("reasoning_effort")
        if env_effort:
            self.reasoning_effort = env_effort
        elif isinstance(config_effort, str) and config_effort:
            self.reasoning_effort = config_effort
        else:
            self.reasoning_effort = "medium"
        debug_env = (
            os.environ.get("AI_DEBUG_REASONING") or os.environ.get("AI_DEBUG_API")
        )
        self._debug_api = bool(debug_env)
        self._debug_stream: TextIO = sys.stderr

    def _api_debug(self, message: str) -> None:
        if self._debug_api:
            print(f"[openai-debug] {message}", file=self._debug_stream)

    def enable_api_debug(self, stream: TextIO) -> None:
        self._debug_api = True
        self._debug_stream = stream

    # Conversation -----------------------------------------------------
    def run_conversation(self, prompt: str, scope: Optional[str]) -> int:
        raw_prompt = (prompt or "").strip()
        if not raw_prompt:
            self.renderer.display_info("Provide a question or instruction.")
            return 1

        self.renderer.display_user_prompt(raw_prompt)

        repo_root = Path.cwd().resolve()
        context_settings = self.config.get("context_settings", {})
        context_max_bytes = int(context_settings.get("max_bytes", MAX_READ_BYTES))
        context_default_limit = int(
            context_settings.get("read_limit", DEFAULT_READ_LIMIT)
        )
        include_listing = bool(context_settings.get("include_listing", False))

        try:
            scope_root, scope_label = self._resolve_scope(scope, repo_root)
        except FileNotFoundError as exc:
            self.renderer.display_error(f"Scope path {exc} does not exist.")
            return 1
        except ValueError as exc:
            self.renderer.display_error(str(exc))
            return 1

        collected = collect_context(
            scope_root,
            limit_bytes=context_max_bytes,
            default_limit=context_default_limit,
            include_listing=include_listing,
        )
        prompt_context = format_context_for_prompt(collected)

        model_id = resolve_model(
            "conversation", self.config, default_model=self.default_model
        )

        scope_sentence = (
            "Focus on the entire repository."
            if scope_label == "repository root"
            else f"Scope: {scope_label}."
        )

        system_prompt = textwrap.dedent(
            f"""
            You are Codex CLI operating locally. You can call tools to read files, write files,
            update plans, or execute sandboxed shell commands. IMPORTANT: when you need to
            create or modify files you MUST call the `write` tool (alias: `write_file`) with the full content (not apply_patch). Do not
            claim success unless the tool call succeeds. Maintain an explicit plan when useful
            using `update_plan`. Always cite relevant files.
            {scope_sentence}
            """
        ).strip()

        conversation_items: List[Dict[str, Any]] = []
        plan_state: Dict[str, Any] = {"plan": None}
        latest_instruction = raw_prompt
        pending_user_message: Optional[str] = "\n".join(
            [
                "Repository snapshot:",
                prompt_context,
                "",
                "Task:",
                raw_prompt,
                "",
                "If files must change, call `write` (or `write_file`) with the full content and wait for confirmation.",
            ]
        )
        pending_context_update: Optional[str] = None
        context_dirty = False
        warned_no_write = False
        buffered_shell_messages: List[str] = []
        skip_model_request = False

        while True:
            rendered_messages: set[str] = set()
            displayed_current_cycle = False
            if context_dirty:
                collected = collect_context(
                    scope_root,
                    limit_bytes=context_max_bytes,
                    default_limit=context_default_limit,
                    include_listing=include_listing,
                )
                prompt_context = format_context_for_prompt(collected)
                pending_context_update = prompt_context
                context_dirty = False

            if pending_context_update:
                conversation_items.append(
                    self._make_user_message(
                        "Updated repository snapshot:\n" + pending_context_update
                    )
                )
                pending_context_update = None

            if pending_user_message:
                conversation_items.append(self._make_user_message(pending_user_message))
                pending_user_message = None

            conversation_payload = cast(Any, conversation_items)
            tools_payload = cast(Any, TOOL_DEFINITIONS)
            tool_call_handled = False
            assistant_messages: list[tuple[str, Optional[str], str]] = []
            assistant_stream_buffers: dict[str, str] = {}
            assistant_stream_cache: dict[str, str] = {}
            streamed_render_keys: set[str] = set()
            previous_message: Optional[str] = None
            pending_reasoning_queue: list[Dict[str, Any]] = []

            if skip_model_request:
                skip_model_request = False
            else:
                response = None
                loader_started = False
                reasoning_buffers: dict[str, str] = {}

                try:
                    if not self.show_reasoning:
                        self.renderer.start_loader()
                        loader_started = True

                    reasoning_payload = None
                    if self.show_reasoning and self.reasoning_effort:
                        reasoning_payload = {
                            "effort": self.reasoning_effort,
                            "summary": "auto",
                        }
                    reasoning_arg = cast(Any, reasoning_payload) if reasoning_payload else None
                    self._api_debug(
                        "stream request model=%s items=%d"
                        % (model_id, len(conversation_items))
                    )

                    with self.client.responses.stream(
                        model=model_id,
                        instructions=system_prompt,
                        input=conversation_payload,
                        tools=tools_payload,
                        tool_choice="auto",
                        reasoning=reasoning_arg,
                    ) as stream:
                        for event in stream:
                            event_type = getattr(event, "type", "")
                            self._api_debug(f"event type={event_type}")

                            if event_type in {
                                "response.reasoning_text.delta",
                                "response.reasoning_summary_text.delta",
                            }:
                                if not self.show_reasoning:
                                    continue
                                text = getattr(event, "delta", "")
                                if not text:
                                    continue
                                suffix = "summary" if "summary" in event_type else "text"
                                part_key = self._reasoning_key(event, suffix=suffix)
                                self._api_debug(
                                    f"delta id={part_key} suffix={suffix} len={len(text)}"
                                )
                                if part_key not in reasoning_buffers:
                                    reasoning_buffers[part_key] = ""
                                    self.renderer.start_reasoning(part_key)
                                reasoning_buffers[part_key] += text
                                self.renderer.update_reasoning(part_key, text)
                            elif event_type in {
                                "response.reasoning_text.done",
                                "response.reasoning_summary_text.done",
                            }:
                                if not self.show_reasoning:
                                    continue
                                suffix = "summary" if "summary" in event_type else "text"
                                part_key = self._reasoning_key(event, suffix=suffix)
                                final_text = getattr(event, "text", "") or reasoning_buffers.get(part_key, "")
                                self._api_debug(
                                    f"done id={part_key} suffix={suffix} len={len(final_text)}"
                                )
                                self.renderer.finish_reasoning(part_key, final_text.strip() or None)
                                reasoning_buffers.pop(part_key, None)
                            elif event_type in {
                                "response.reasoning_summary_part.added",
                                "response.reasoning_summary_part.done",
                            }:
                                self._api_debug(
                                    "event reasoning summary part received; skipping"
                                )
                                continue
                            elif event_type == "response.completed":
                                response = getattr(event, "response", None)
                            elif event_type == "response.output_text.delta":
                                delta = getattr(event, "delta", "")
                                if not delta:
                                    continue
                                if loader_started:
                                    self.renderer.stop_loader()
                                    loader_started = False
                                key = self._assistant_key(event)
                                if key not in assistant_stream_buffers:
                                    assistant_stream_buffers[key] = ""
                                    self.renderer.start_assistant_stream(key)
                                assistant_stream_buffers[key] += delta
                                self.renderer.update_assistant_stream(key, delta)
                                self._api_debug(
                                    f"assistant delta id={key} len={len(delta)}"
                                )
                            elif event_type == "response.output_text.done":
                                key = self._assistant_key(event)
                                final_text = getattr(event, "text", "")
                                buffer_text = assistant_stream_buffers.pop(key, "")
                                stream_text = final_text or buffer_text
                                self.renderer.finish_assistant_stream(key, stream_text)
                                message_id = getattr(event, "item_id", None)
                                cache_key = message_id if isinstance(message_id, str) else key
                                if stream_text:
                                    assistant_stream_cache[cache_key] = stream_text
                                streamed_render_keys.add(cache_key)
                                self._api_debug(
                                    f"assistant done id={key} len={len(stream_text)}"
                                )
                            elif event_type.startswith("response.function_call_arguments."):
                                delta = getattr(event, "delta", "")
                                item_id = getattr(event, "item_id", None)
                                name = getattr(event, "name", "")
                                self._api_debug(
                                    f"function_call event={event_type} item={item_id} name={name} len={len(delta) if isinstance(delta, str) else 0}"
                                )
                                if event_type.endswith(".done"):
                                    response = getattr(event, "response", response)
                            elif event_type == "response.error":
                                message = getattr(event, "error", None)
                                if message:
                                    err_text = getattr(message, "message", str(message))
                                    self.renderer.display_error(err_text)
                                response = None
                                break

                        if response is None:
                            response = getattr(stream, "response", None) or getattr(stream, "final_response", None)
                        self._api_debug(
                            "stream exit status=%s"
                            % (getattr(response, "status", None) if response else None)
                        )

                    if self.show_reasoning:
                        for reasoning_id, text in list(reasoning_buffers.items()):
                            self._api_debug(
                                f"cleanup id={reasoning_id} len={len(text)}"
                            )
                            self.renderer.finish_reasoning(reasoning_id, text.strip() or None)
                            reasoning_buffers.pop(reasoning_id, None)
                except KeyboardInterrupt:
                    if self.show_reasoning:
                        for reasoning_id, text in list(reasoning_buffers.items()):
                            self.renderer.finish_reasoning(reasoning_id, text.strip() or None)
                    if loader_started:
                        self.renderer.stop_loader()
                    self.renderer.display_info("\nInterrupted by user.")
                    return 130
                except Exception as exc:
                    if self.show_reasoning:
                        for reasoning_id, text in list(reasoning_buffers.items()):
                            self.renderer.finish_reasoning(reasoning_id, text.strip() or None)
                    if loader_started:
                        self.renderer.stop_loader()
                    self.renderer.display_error(f"Error: {exc}")
                    return 1
                finally:
                    if loader_started:
                        self.renderer.stop_loader()

                if response is None:
                    continue

                for item in getattr(response, "output", []) or []:
                    item_type = getattr(item, "type", "")

                    if item_type == "message":
                        raw_item_id = getattr(item, "id", None)
                        text_parts: List[str] = []
                        for block in getattr(item, "content", []) or []:
                            if getattr(block, "type", "").endswith("text"):
                                text_parts.append(getattr(block, "text", ""))
                        text = "".join(text_parts).strip()
                        pending_reasoning_queue.clear()
                        if text:
                            render_key = (
                                raw_item_id
                                if isinstance(raw_item_id, str)
                                else self._assistant_message_key(item)
                            )
                            cached_text = assistant_stream_cache.pop(render_key, None)
                            final_text = cached_text or text
                            assistant_messages.append((final_text, raw_item_id, render_key))
                            if cached_text is not None:
                                streamed_render_keys.add(render_key)
                            self._api_debug(
                                f"assistant message id={render_key} len={len(final_text)}"
                            )
                            conversation_items.append(
                                self._make_assistant_message(final_text)
                            )

                    elif item_type in {"tool_call", "function_call"}:
                        item_payload = self._convert_response_item(item)
                        raw_item_id = getattr(item, "id", None)
                        raw_call_id = getattr(item, "call_id", None) or raw_item_id
                        tool_name = getattr(item, "name", "")
                        call_id = str(raw_call_id or f"tool-{tool_name}")
                        arguments_payload = item_payload.get("arguments", {})
                        if pending_reasoning_queue:
                            conversation_items.append(pending_reasoning_queue.pop(0))
                        conversation_items.append(
                            self._make_tool_call_item(
                                call_id=call_id,
                                tool_name=tool_name,
                                arguments=arguments_payload,
                                raw_id=raw_item_id,
                            )
                        )
                        result_text, mutated = self._handle_tool_call(
                            tool_name,
                            arguments_payload,
                            base_root=repo_root,
                            default_root=scope_root if scope else repo_root,
                            plan_state=plan_state,
                            latest_instruction=latest_instruction,
                        )
                        conversation_items.append(
                            self._make_tool_result_message(call_id, result_text)
                        )
                        if mutated:
                            context_dirty = True
                        tool_call_handled = True

                    elif item_type == "reasoning":
                        reasoning_payload = self._convert_response_item(item)
                        sanitized = {
                            key: value
                            for key, value in reasoning_payload.items()
                            if key in {"type", "id", "summary", "content"}
                            and value is not None
                        }
                        sanitized.setdefault("type", "reasoning")
                        pending_reasoning_queue.append(sanitized)
                        # Summary is available via reasoning stream; avoid duplicate prints here.

                pending_reasoning_queue.clear()
            # end if not skip_model_request

            if tool_call_handled:
                continue

            manual_mutation = False
            for message_text, message_id, render_key in assistant_messages:
                if (
                    render_key not in rendered_messages
                    and render_key not in streamed_render_keys
                    and not displayed_current_cycle
                ):
                    self.renderer.display_assistant_message(message_text)
                    rendered_messages.add(render_key)
                    displayed_current_cycle = True
                previous_message = message_text
                for filename, content in self._detect_generated_files(message_text):
                    status = self._apply_file_update(
                        filename,
                        content,
                        base_root=repo_root,
                        default_root=scope_root if scope else repo_root,
                        auto_apply=self._instruction_implies_write(latest_instruction),
                    )
                    if status == "applied":
                        manual_mutation = True
                    elif status.startswith("error"):
                        self.renderer.display_error(status)
            if manual_mutation:
                context_dirty = True
                warned_no_write = False

            if assistant_messages and not manual_mutation:
                if not warned_no_write and any(
                    re.search(
                        r"\b(created|saved|written|added|generated)\b",
                        msg_text,
                        re.IGNORECASE,
                    )
                    for msg_text, _, _ in assistant_messages
                ):
                    pending_user_message = "It appears no files changed. Please call the `write` tool (alias: `write_file`) with the full contents so the file can be created."
                    warned_no_write = True
                    continue

            follow_up = self.renderer.prompt_follow_up()
            if follow_up is None:
                return 0
            follow_up = follow_up.strip()
            if not follow_up:
                return 0

            self.renderer.display_user_prompt(follow_up)

            warned_no_write = False

            if follow_up.startswith("!"):
                command_text = follow_up[1:].strip()
                if not command_text:
                    continue

                try:
                    self._api_debug(f"shell command={command_text}")
                    result = run_sandboxed_bash(
                        command_text,
                        cwd=scope_root if scope else repo_root,
                        scope_root=repo_root,
                        timeout=30,
                        max_output_bytes=20000,
                    )
                    formatted = format_command_result(result)
                    self._api_debug(
                        f"shell result len={len(formatted)} truncated={formatted[:120]!r}"
                    )
                    preview_message = (
                        "Executed shell command: `"
                        + command_text
                        + "`\n"
                        + ("Output:\n```\n" + formatted + "\n```" if formatted.strip() else "Output: (no stdout)")
                    )
                    buffered_shell_messages.append(preview_message)
                    skip_model_request = True
                except CommandRejected as exc:
                    self.renderer.display_error(f"command rejected: {exc}")
                except Exception as exc:
                    self.renderer.display_error(f"error running command: {exc}")
                continue

            warned_no_write = False

            latest_instruction = follow_up
            if buffered_shell_messages:
                for msg in buffered_shell_messages:
                    conversation_items.append(self._make_user_message(msg))
                buffered_shell_messages.clear()
            for completion_msg in self.renderer.consume_completion_messages():
                conversation_items.append(self._make_user_message(completion_msg))
            pending_user_message = (
                "Follow-up instruction:\n"
                + follow_up
                + "\n\nReminder: use the `write` tool (or `write_file`) with full file contents when files must change."
            )

    # Edit workflow ----------------------------------------------------
    def run_edit(
        self,
        path: str,
        instruction: str,
        *,
        model_override: Optional[str] = None,
    ) -> int:
        target_path = Path(path).expanduser()
        if target_path.is_dir():
            self.renderer.display_info(
                f"{target_path} is a directory, not a file. Try harder."
            )
            return 1

        try:
            current_text = (
                target_path.read_text(encoding="utf-8") if target_path.exists() else ""
            )
        except UnicodeDecodeError:
            self.renderer.display_info(f"{target_path} isn't UTF-8 text.")
            return 1
        except OSError as exc:
            self.renderer.display_error(f"Couldn't read {target_path}: {exc}")
            return 1

        effective_model = resolve_model(
            "edit", self.config, model_override, self.default_model
        )
        system_message = (
            "You rewrite files. Return only the complete updated file content. "
            "No explanations, no code fences, no commentary."
        )
        user_message = (
            f"File: {target_path}\n"
            "Instruction:\n"
            f"{instruction}\n\n"
            "Original file contents:\n"
            f"{current_text}"
        )

        self.renderer.start_loader()
        content = ""
        self._api_debug(
            f"edit request model={effective_model} path={target_path} instruction_len={len(instruction)}"
        )

        try:
            if self._is_responses_model(effective_model):
                response = self.client.responses.create(  # type: ignore[arg-type]
                    model=effective_model,
                    input=f"{system_message}\n\n{user_message}",
                )
                content = self._coalesce_responses_text(response)
                self._api_debug(
                    f"edit response status={getattr(response, 'status', None)} output_len={len(content)}"
                )
            else:
                chat_response = self.client.chat.completions.create(
                    model=effective_model,
                    messages=[
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": user_message},
                    ],
                )
                if chat_response.choices:
                    choice = chat_response.choices[0]
                    content_obj = getattr(choice.message, "content", None)
                    content = content_obj if isinstance(content_obj, str) else ""
                self._api_debug(
                    f"edit response chat choices={len(chat_response.choices) if hasattr(chat_response, 'choices') else 0} output_len={len(content)}"
                )
        except Exception as exc:
            self.renderer.display_error(f"Error: {exc}. The API tripped over itself.")
            return 1
        finally:
            self.renderer.stop_loader()

        if not content:
            self.renderer.display_info("Model returned no content. Aborting.")
            return 1

        proposed_text = self._strip_code_fence(content)
        if proposed_text == "":
            self.renderer.display_info(
                "Model returned empty content. Not touching your file."
            )
            return 1
        if proposed_text == current_text:
            self.renderer.display_info(
                "Model produced identical content. Nothing to do."
            )
            return 0

        display_path = (
            target_path.relative_to(Path.cwd())
            if target_path.is_absolute()
            else target_path
        )
        status = self.renderer.review_file_update(
            target_path=target_path,
            display_path=display_path,
            old_text=current_text,
            new_text=proposed_text,
            auto_apply=self._instruction_implies_write(instruction),
        )

        if status == "user_rejected":
            extra = self.renderer.prompt_text("add_context >>> ")
            if extra:
                combined_instruction = f"{instruction}\n\nAdditional context provided after review:\n{extra}"
                return self.run_edit(
                    path, combined_instruction, model_override=model_override
                )
            return 0
        if status.startswith("error"):
            self.renderer.display_error(status)
            return 1
        return 0

    # Helpers ----------------------------------------------------------
    def _is_responses_model(self, model: str) -> bool:
        return model.endswith("codex") or model.startswith("gpt-5")

    def _resolve_scope(self, scope: Optional[str], repo_root: Path) -> tuple[Path, str]:
        if not scope:
            return repo_root, "repository root"

        candidate = Path(scope).expanduser()
        candidate = (
            (repo_root / candidate).resolve()
            if not candidate.is_absolute()
            else candidate.resolve()
        )

        try:
            candidate.relative_to(repo_root)
        except ValueError as exc:
            raise ValueError("Scope path must be inside the repository") from exc

        if not candidate.exists():
            raise FileNotFoundError(candidate)

        if candidate.is_dir():
            label = str(candidate.relative_to(repo_root)) or "."
            return candidate, label

        return candidate.parent, str(candidate.relative_to(repo_root))

    def _apply_file_update(
        self,
        filename: str,
        content: str,
        *,
        base_root: Path,
        default_root: Path,
        auto_apply: bool,
    ) -> str:
        path = Path(filename)
        path = (
            (default_root / path).resolve()
            if not path.is_absolute()
            else path.resolve()
        )

        try:
            relative = path.relative_to(base_root)
        except ValueError:
            self.renderer.display_info(
                f"[skip] refusing to modify outside project root: {path}"
            )
            return "skipped_out_of_scope"

        try:
            old_text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            old_text = ""
        except Exception as exc:
            message = f"error: failed to read {relative}: {exc}"
            self.renderer.display_error(message)
            return message

        return self.renderer.review_file_update(
            target_path=path,
            display_path=relative,
            old_text=old_text,
            new_text=content,
            auto_apply=auto_apply,
        )

    def _handle_tool_call(
        self,
        tool_name: str,
        arguments: Any,
        *,
        base_root: Path,
        default_root: Path,
        plan_state: Dict[str, Any],
        latest_instruction: str,
    ) -> tuple[str, bool]:
        args = self._parse_arguments(arguments, tool_name)
        mutated = False
        self._api_debug(
            f"tool_call name={tool_name} args_preview={str(args)[:200]}"
        )

        if tool_name == "read_file":
            path_arg = args.get("path")
            if not path_arg:
                return "error: missing path", False
            path = Path(path_arg)
            path = (
                (default_root / path).resolve()
                if not path.is_absolute()
                else path.resolve()
            )
            try:
                path.relative_to(base_root)
            except ValueError:
                return f"error: path outside project root ({path})", False

            limit = int(args.get("limit", 8000) or 8000)
            offset = int(args.get("offset", 0) or 0)
            try:
                data = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                return f"error: failed to read {path}: {exc}", False

            snippet = data[offset : offset + limit]
            preview = f"Contents of {path.relative_to(base_root)}\n```\n{snippet}\n```"
            return preview, False

        if tool_name in {"write", "write_file"}:
            path_arg = args.get("filePath") or args.get("path")
            contents = args.get("content")
            if contents is None:
                contents = args.get("contents")
            if not path_arg or contents is None:
                return "error: missing file path or contents", False
            status = self._apply_file_update(
                path_arg,
                contents,
                base_root=base_root,
                default_root=default_root,
                auto_apply=self._instruction_implies_write(latest_instruction),
            )
            mutated = status == "applied"
            self._api_debug(
                f"tool_result name={tool_name} mutated={mutated} len={len(contents)}"
            )
            return status, mutated

        if tool_name == "apply_patch":
            patch_text = args.get("patch") or args.get("input")
            if not patch_text:
                return "error: missing patch", False
            self.renderer.display_info("# apply_patch proposal\n" + patch_text)
            if not self.renderer.prompt_confirm(
                "Apply patch? [y/N]: ", default_no=True
            ):
                return "user_rejected", False
            try:
                proc = subprocess.run(
                    ["patch", "-p0", "--batch", "--forward"],
                    input=patch_text,
                    text=True,
                    cwd=base_root,
                    capture_output=True,
                )
            except FileNotFoundError:
                return "error: 'patch' command not available", False
            if proc.returncode != 0:
                if proc.stdout:
                    self.renderer.display_info(proc.stdout)
                if proc.stderr:
                    self.renderer.display_error(proc.stderr)
                return f"error: patch failed (status {proc.returncode})", False
            if proc.stdout:
                self.renderer.display_info(proc.stdout)
            return "applied", True

        if tool_name == "shell":
            result, mutated = self._handle_shell_command(
                args,
                base_root=base_root,
                default_root=default_root,
            )
            return result, mutated

        if tool_name == "update_plan":
            plan = (args.get("plan") or "").strip()
            explanation = (args.get("explanation") or "").strip() or None
            plan_state["plan"] = plan
            self.renderer.display_plan_update(plan, explanation)
            response = "plan updated"
            if explanation:
                response += f"; notes: {explanation}"
            self._api_debug("tool_result name=update_plan mutated=False")
            return response, False

        return f"error: unknown tool '{tool_name}'", False

    def _handle_shell_command(
        self,
        args: Dict[str, Any],
        *,
        base_root: Path,
        default_root: Path,
    ) -> tuple[str, bool]:
        command = args.get("command")
        if isinstance(command, str):
            command_str = command
        elif isinstance(command, list):
            command_str = " ".join(shlex.quote(str(part)) for part in command)
        else:
            return "error: invalid command; expected string or list", False

        workdir_arg = args.get("workdir")
        workdir = Path(workdir_arg).expanduser() if workdir_arg else default_root
        workdir = (
            (default_root / workdir).resolve()
            if not workdir.is_absolute()
            else workdir.resolve()
        )
        try:
            workdir.relative_to(base_root)
        except ValueError:
            return f"error: workdir outside project root ({workdir})", False

        try:
            timeout_seconds = max(1, int(os.environ.get("AI_BASH_MAX_SECONDS", "15")))
        except (TypeError, ValueError):
            timeout_seconds = 15
        try:
            max_output_bytes = max(
                1, int(os.environ.get("AI_BASH_MAX_OUTPUT", "20000"))
            )
        except (TypeError, ValueError):
            max_output_bytes = 20000

        timeout_override = args.get("timeout_ms")
        if timeout_override is not None:
            try:
                timeout_seconds = max(1, int(timeout_override) // 1000)
            except Exception:
                pass

        try:
            result = run_sandboxed_bash(
                command_str,
                cwd=workdir,
                scope_root=base_root,
                timeout=timeout_seconds,
                max_output_bytes=max_output_bytes,
            )
            formatted = format_command_result(result)
            self.renderer.display_shell_output(formatted)
            return formatted, False
        except CommandRejected as exc:
            message = f"command rejected: {exc}"
            self.renderer.display_error(message)
            return message, False

    def _parse_arguments(self, arguments: Any, tool_name: str) -> Dict[str, Any]:
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError as exc:
                raise ValueError(f"{tool_name}: invalid arguments JSON ({exc})")
            return parsed
        if isinstance(arguments, dict):
            return arguments
        return {}

    def _detect_generated_files(self, message: str) -> List[tuple[str, str]]:
        pattern = re.compile(
            r"(?:save|write|create|add|generate|produce)[^\n]{0,160}?\b(?:as|to|in)\s+`?([A-Za-z0-9._\-/]+)`?(?::)?",
            re.IGNORECASE,
        )
        lines = message.splitlines()
        i = 0
        results: List[tuple[str, str]] = []
        while i < len(lines):
            match = pattern.search(lines[i])
            if not match:
                i += 1
                continue

            filename = match.group(1).strip().rstrip(":").strip()
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            if j >= len(lines):
                i += 1
                continue
            j += 1
            start = j
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            if j >= len(lines):
                break
            content = "\n".join(lines[start:j]).rstrip()
            results.append((filename, content))
            i = j + 1
        return results

    def _instruction_implies_write(self, text: str) -> bool:
        normalized = text.lower()
        return bool(
            re.search(
                r"\b(write|create|add|generate|produce|save|append|commit|apply|patch|update|make|build|draft|add it|addit|writeit)\b",
                normalized,
            )
        )

    def _reasoning_key(self, event: Any, suffix: str = "text") -> str:
        item_id = getattr(event, "item_id", "reasoning")
        if suffix == "summary":
            index = getattr(event, "summary_index", getattr(event, "output_index", 0))
            label = "summary"
        else:
            index = getattr(event, "content_index", getattr(event, "output_index", 0))
            label = "text"
        return f"{item_id}:{label}:{index}"

    def _assistant_key(self, event: Any) -> str:
        item_id = getattr(event, "item_id", "assistant")
        content_index = getattr(event, "content_index", getattr(event, "output_index", 0))
        return f"{item_id}:{content_index}"

    def _assistant_message_key(self, item: Any) -> str:
        item_id = getattr(item, "id", "assistant")
        return f"{item_id}:0"

    def _coalesce_responses_text(self, response: Any) -> str:
        if response is None:
            return ""
        if hasattr(response, "output_text"):
            text = getattr(response, "output_text")
            if isinstance(text, str) and text.strip():
                return text
        if hasattr(response, "model_dump"):
            data = response.model_dump()
        elif hasattr(response, "dict"):
            data = response.dict()
        else:
            data = response

        def _from_output(obj: Any) -> str:
            content_chunks: List[str] = []
            if isinstance(obj, dict):
                output = obj.get("output") or obj.get("choices") or obj.get("content")
                if isinstance(output, list):
                    for item in output:
                        text = _from_output(item)
                        if text:
                            content_chunks.append(text)
                elif isinstance(output, dict):
                    text = _from_output(output)
                    if text:
                        content_chunks.append(text)
                text_value = obj.get("text")
                if isinstance(text_value, str):
                    content_chunks.append(text_value)
                return "".join(content_chunks)
            if isinstance(obj, list):
                return "".join(_from_output(item) for item in obj)
            if isinstance(obj, str):
                return obj
            return ""

        return _from_output(data).strip()

    def _strip_code_fence(self, raw_response: str) -> str:
        text = (raw_response or "").strip()
        if text.startswith("```"):
            fence_break = text.find("\n")
            if fence_break == -1:
                return ""
            text = text[fence_break + 1 :]
            text = text.rsplit("```", 1)[0]
        return text.replace("\r\n", "\n").strip("\n")

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

    def _make_user_message(self, text: str) -> Dict[str, Any]:
        return {"role": "user", "content": [{"type": "input_text", "text": text}]}

    def _make_assistant_message(self, text: str) -> Dict[str, Any]:
        return {"role": "assistant", "content": [{"type": "output_text", "text": text}]}

    def _make_tool_result_message(self, call_id: str, text: str) -> Dict[str, Any]:
        return {
            "type": "function_call_output",
            "call_id": call_id,
            "output": text,
        }

    def _make_tool_call_item(
        self,
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
