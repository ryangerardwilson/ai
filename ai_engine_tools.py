from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, TextIO

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

    def finish_reasoning(
        self, reasoning_id: str, final: Optional[str] = None
    ) -> None: ...

    def start_assistant_stream(self, stream_id: str) -> None: ...

    def update_assistant_stream(self, stream_id: str, delta: str) -> None: ...

    def finish_assistant_stream(
        self, stream_id: str, final_text: Optional[str] = None
    ) -> None: ...

    def enable_debug_logging(self, stream: TextIO) -> None: ...

    def start_hotkey_listener(self) -> None: ...

    def stop_hotkey_listener(self) -> None: ...

    def poll_hotkey_event(self) -> Optional[str]: ...


@dataclass
class ToolRuntime:
    renderer: RendererProtocol
    base_root: Path
    default_root: Path
    plan_state: Dict[str, Any]
    latest_instruction: str
    debug: Callable[[str], None] = field(default=lambda _msg: None)


def instruction_implies_write(text: str) -> bool:
    normalized = text.lower()
    return bool(
        re.search(
            r"\b(write|create|add|generate|produce|save|append|commit|apply|patch|update|make|build|draft|add it|addit|writeit)\b",
            normalized,
        )
    )


def detect_generated_files(message: str) -> List[tuple[str, str]]:
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


def parse_arguments(arguments: Any, tool_name: str) -> Dict[str, Any]:
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"{tool_name}: invalid arguments JSON ({exc})")
        return parsed
    if isinstance(arguments, dict):
        return arguments
    return {}


def handle_tool_call(
    tool_name: str,
    arguments: Any,
    runtime: ToolRuntime,
) -> tuple[str, bool]:
    args = parse_arguments(arguments, tool_name)
    runtime.debug(f"tool_call name={tool_name} args_preview={str(args)[:200]}")

    if tool_name == "read_file":
        path_arg = args.get("path")
        if not path_arg:
            return "error: missing path", False
        path = Path(path_arg)
        path = (
            (runtime.default_root / path).resolve()
            if not path.is_absolute()
            else path.resolve()
        )
        try:
            path.relative_to(runtime.base_root)
        except ValueError:
            return f"error: path outside project root ({path})", False

        limit = int(args.get("limit", 8000) or 8000)
        offset = int(args.get("offset", 0) or 0)
        try:
            data = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"error: failed to read {path}: {exc}", False

        snippet = data[offset : offset + limit]
        preview = (
            f"Contents of {path.relative_to(runtime.base_root)}\n```\n{snippet}\n```"
        )
        return preview, False

    if tool_name in {"write", "write_file"}:
        path_arg = args.get("filePath") or args.get("path")
        contents = args.get("content")
        if contents is None:
            contents = args.get("contents")
        if not path_arg or contents is None:
            return "error: missing file path or contents", False
        auto_apply = instruction_implies_write(runtime.latest_instruction)
        status = apply_file_update(
            path_arg,
            contents,
            runtime,
            auto_apply=auto_apply,
        )
        mutated = status == "applied"
        runtime.debug(
            f"tool_result name={tool_name} mutated={mutated} len={len(contents)}"
        )
        return status, mutated

    if tool_name == "apply_patch":
        patch_text = args.get("patch") or args.get("input")
        if not patch_text:
            return "error: missing patch", False
        runtime.renderer.display_info("# apply_patch proposal\n" + patch_text)
        if not runtime.renderer.prompt_confirm("Apply patch? [y/N]: ", default_no=True):
            return "user_rejected", False
        try:
            proc = subprocess.run(
                ["patch", "-p0", "--batch", "--forward"],
                input=patch_text,
                text=True,
                cwd=runtime.base_root,
                capture_output=True,
            )
        except FileNotFoundError:
            return "error: 'patch' command not available", False
        if proc.returncode != 0:
            if proc.stdout:
                runtime.renderer.display_info(proc.stdout)
            if proc.stderr:
                runtime.renderer.display_error(proc.stderr)
            return f"error: patch failed (status {proc.returncode})", False
        if proc.stdout:
            runtime.renderer.display_info(proc.stdout)
        return "applied", True

    if tool_name == "shell":
        return handle_shell_command(args, runtime)

    if tool_name == "update_plan":
        plan = (args.get("plan") or "").strip()
        explanation = (args.get("explanation") or "").strip() or None
        runtime.plan_state["plan"] = plan
        runtime.renderer.display_plan_update(plan, explanation)
        response = "plan updated"
        if explanation:
            response += f"; notes: {explanation}"
        runtime.debug("tool_result name=update_plan mutated=False")
        return response, False

    return f"error: unknown tool '{tool_name}'", False


def apply_file_update(
    filename: str,
    content: str,
    runtime: ToolRuntime,
    *,
    auto_apply: bool,
) -> str:
    path = Path(filename)
    path = (
        (runtime.default_root / path).resolve()
        if not path.is_absolute()
        else path.resolve()
    )

    try:
        relative = path.relative_to(runtime.base_root)
    except ValueError:
        runtime.renderer.display_info(
            f"[skip] refusing to modify outside project root: {path}"
        )
        return "skipped_out_of_scope"

    try:
        old_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        old_text = ""
    except Exception as exc:
        message = f"error: failed to read {relative}: {exc}"
        runtime.renderer.display_error(message)
        return message

    status = runtime.renderer.review_file_update(
        target_path=path,
        display_path=relative,
        old_text=old_text,
        new_text=content,
        auto_apply=auto_apply,
    )

    if status == "delete_requested":
        return delete_path_via_shell(path, runtime)

    return status


def delete_path_via_shell(path: Path, runtime: ToolRuntime) -> str:
    try:
        relative = path.relative_to(runtime.base_root)
    except ValueError:
        return "error: delete outside project root"

    rm_cmd = f"rm {shlex.quote(str(relative))}"
    try:
        result = run_sandboxed_bash(
            rm_cmd,
            cwd=runtime.base_root,
            scope_root=runtime.base_root,
            timeout=30,
            max_output_bytes=20000,
        )
    except CommandRejected as exc:
        return f"error: {exc}"
    except Exception as exc:
        return f"error: failed to delete {relative}: {exc}"

    formatted = format_command_result(result)
    runtime.renderer.display_info(f"$ {rm_cmd}")
    if formatted.strip():
        runtime.renderer.display_shell_output(formatted)

    if result.exit_code != 0:
        return f"error: rm exited with {result.exit_code}"
    return "applied"


def handle_shell_command(
    args: Dict[str, Any],
    runtime: ToolRuntime,
) -> tuple[str, bool]:
    command = args.get("command")
    if isinstance(command, str):
        command_str = command
    elif isinstance(command, list):
        command_str = " ".join(shlex.quote(str(part)) for part in command)
    else:
        return "error: invalid command; expected string or list", False

    workdir_arg = args.get("workdir")
    workdir = Path(workdir_arg).expanduser() if workdir_arg else runtime.default_root
    workdir = (
        (runtime.default_root / workdir).resolve()
        if not workdir.is_absolute()
        else workdir.resolve()
    )
    try:
        workdir.relative_to(runtime.base_root)
    except ValueError:
        return f"error: workdir outside project root ({workdir})", False

    try:
        timeout_seconds = max(1, int(os.environ.get("AI_BASH_MAX_SECONDS", "15")))
    except (TypeError, ValueError):
        timeout_seconds = 15
    try:
        max_output_bytes = max(1, int(os.environ.get("AI_BASH_MAX_OUTPUT", "20000")))
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
            scope_root=runtime.base_root,
            timeout=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        formatted = format_command_result(result)
        rendered_parts = [f"$ {command_str}"]
        if formatted.strip():
            rendered_parts.append(formatted)
        else:
            rendered_parts.append("(no output)")
        rendered = "\n\n".join(rendered_parts)
        runtime.renderer.display_shell_output(rendered)
        return rendered, False
    except CommandRejected as exc:
        message = f"command rejected: {exc}"
        runtime.renderer.display_error(message)
        return message, False


__all__ = [
    "RendererProtocol",
    "TOOL_DEFINITIONS",
    "ToolRuntime",
    "apply_file_update",
    "delete_path_via_shell",
    "detect_generated_files",
    "handle_shell_command",
    "handle_tool_call",
    "instruction_implies_write",
    "parse_arguments",
]
