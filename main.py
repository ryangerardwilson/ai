#!/usr/bin/env python3

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shlex
import openai
import sys
import time
import subprocess
import tempfile
import signal
import threading
import textwrap
from pathlib import Path
from typing import Any, Dict, Sequence, List

try:
    from _version import __version__
except Exception:  # pragma: no cover - fallback when running from source
    __version__ = "0.0.0"

from config_loader import (
    load_config,
    DEFAULT_MODELS,
    DEFAULT_SYSTEM_PROMPT,
)
from config_paths import get_config_path
from bash_executor import (
    CommandRejected,
    format_command_result,
    run_sandboxed_bash,
)
from contextualizer import (
    collect_context,
    format_context_for_display,
    format_context_for_prompt,
)

INSTALL_SH_URL = "https://raw.githubusercontent.com/ryangerardwilson/ai/main/install.sh"


COLOR_ADD = "\033[97m"  # bright white
COLOR_REMOVE = "\033[37m"  # light gray
COLOR_CONTEXT = "\033[90m"  # dark gray
COLOR_RESET = "\033[0m"
DEFAULT_COLOR = "\033[1;36m"

PRIMARY_FLAG_SET = {"-h", "--help", "-v", "--version", "-V", "-u", "--upgrade"}
RESPONSES_ONLY_MODELS = {
    "gpt-5-codex",
    "gpt-5.1-codex",
    "gpt-5.1-codex-mini",
}

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "read_file",
        "description": "Read a text file from the repository.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
                "offset": {"type": "integer", "minimum": 0, "description": "Optional byte offset"},
                "limit": {"type": "integer", "minimum": 1, "description": "Optional byte limit"},
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
                "contents": {"type": "string", "description": "Full replacement file contents"},
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
                "workdir": {"type": "string", "description": "Optional working directory"},
                "timeout_ms": {"type": "integer", "minimum": 1, "description": "Optional timeout in milliseconds"},
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
                "explanation": {"type": "string", "description": "Optional reasoning or notes"},
            },
            "required": ["plan"],
        },
    },
]


def _is_responses_model(model: str) -> bool:
    return model in RESPONSES_ONLY_MODELS


def _print_help() -> None:
    print(
        "ai - Codex-style terminal assistant\n\n"
        "Usage:\n"
        "  ai [SCOPE] \"question or instruction\"\n"
        "      SCOPE (optional) is a file or directory to focus on\n"
        "      When SCOPE is a file, ai proposes edits with diff approval\n"
        "  ai -h            Show this help\n"
        "  ai -v            Show installed version\n"
        "  ai -u            Reinstall the latest release if a newer version exists"
    )


def _run_upgrade() -> int:
    try:
        curl = subprocess.Popen(
            ["curl", "-fsSL", INSTALL_SH_URL],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        print("Upgrade requires curl", file=sys.stderr)
        return 1

    try:
        bash = subprocess.Popen(["bash", "-s", "--", "-u"], stdin=curl.stdout)
        if curl.stdout is not None:
            curl.stdout.close()
    except FileNotFoundError:
        print("Upgrade requires bash", file=sys.stderr)
        curl.terminate()
        curl.wait()
        return 1

    bash_rc = bash.wait()
    curl_rc = curl.wait()

    if curl_rc != 0:
        stderr = (
            curl.stderr.read().decode("utf-8", errors="replace") if curl.stderr else ""
        )
        if stderr:
            sys.stderr.write(stderr)
        return curl_rc

    return bash_rc


def _parse_primary_flags(argv: Sequence[str]) -> tuple[bool, bool, bool]:
    show_help = False
    show_version = False
    do_upgrade = False

    for arg in argv:
        if arg in {"-h", "--help"}:
            show_help = True
        elif arg in {"-v", "--version", "-V"}:
            show_version = True
        elif arg in {"-u", "--upgrade"}:
            do_upgrade = True
        else:
            raise ValueError(f"Unknown flag '{arg}'")

    if sum((show_help, show_version, do_upgrade)) > 1:
        raise ValueError("Flags -h, -v, and -u cannot be combined")

    return show_help, show_version, do_upgrade


def _handle_primary_flags(args: Sequence[str]) -> int | None:
    if not args:
        return None

    if not set(args).issubset(PRIMARY_FLAG_SET):
        return None

    try:
        show_help, show_version, do_upgrade = _parse_primary_flags(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if show_help:
        _print_help()
        return 0
    if show_version:
        print(__version__)
        return 0
    if do_upgrade:
        return _run_upgrade()

    return 0


def resolve_api_key(
    candidate: str | None = None, config: Dict[str, Any] | None = None
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
    config_path = get_config_path()
    print(
        f"Set OPENAI_API_KEY or add 'openai_api_key' to {config_path}.",
        file=sys.stderr,
    )
    sys.exit(1)


def resolve_color(candidate: str | None = None) -> str:
    if candidate:
        return candidate
    env_color = os.environ.get("AI_COLOR")
    if env_color:
        return env_color
    return DEFAULT_COLOR


def resolve_model(
    mode: str,
    config: Dict[str, Any] | None = None,
    override: str | None = None,
) -> str:
    if override:
        return override
    cfg = config or {}
    models_obj = cfg.get("models")
    if isinstance(models_obj, dict):
        candidate = models_obj.get(mode)
        if candidate:
            return str(candidate)
    return DEFAULT_MODELS.get(mode, DEFAULT_MODELS.get("prompt", "gpt-5-mini"))


class AIChat:
    def __init__(
        self,
        model: str | None = None,
        ai_font_color: str | None = None,
        api_key: str | None = None,
        config: Dict[str, Any] | None = None,
        mode: str = "chat",
    ):
        self.config = config or {}
        self.mode = mode
        resolved_model = resolve_model(mode, self.config, model)
        resolved_color = resolve_color(ai_font_color)
        system_prompt = self.config.get("system_instruction", DEFAULT_SYSTEM_PROMPT)

        api_key_value = resolve_api_key(api_key, self.config)
        self.client = openai.OpenAI(api_key=api_key_value)
        self.model = resolved_model
        self.ai_color = resolved_color
        self.reset_color = "\033[0m"
        self.system_prompt = system_prompt
        self.messages = [{"role": "system", "content": self.system_prompt}]
        fd, self.history_file = tempfile.mkstemp(
            prefix="chat_history_", suffix=".txt", dir="/tmp"
        )
        os.close(fd)  # We don't need the fd, just the unique path
        signal.signal(
            signal.SIGINT, self.signal_handler
        )  # Trap Ctrl+C for graceful exit, you klutz

    def signal_handler(self, sig, frame):
        print("\nCtrl+C caught. Cleaning up like a proper Omarchy citizen.")
        self.cleanup_history_file()
        sys.exit(0)

    def cleanup_history_file(self):
        try:
            os.unlink(self.history_file)
        except OSError:
            pass  # Whatever, Omarchy will reboot eventually

    def save_history(self):
        with open(self.history_file, "w") as f:
            for msg in self.messages[1:]:  # Skip system prompt, nobody cares.
                if msg["role"] == "user":
                    f.write(f"QUERY>>> {msg['content']}\n")
                elif msg["role"] == "assistant":
                    f.write(f"AI>>> {msg['content']}\n\n")
            f.write("QUERY>>> ")

    def get_user_input_from_vim(self):
        # Open Vim at the end of the file, cursor at EOL, in insert mode
        subprocess.call(
            ["vim", "+", "-c", "norm G$", "-c", "startinsert!", self.history_file]
        )

        # Read back the file
        try:
            with open(self.history_file, "r") as f:
                content = f.read()
        except FileNotFoundError:
            # If deleted, treat as reset
            return None, True

        # Find the last "QUERY>>> " and split
        if "QUERY>>> " in content:
            # Reverse find the last occurrence
            last_query_pos = content.rfind("QUERY>>> ")
            history_part = content[:last_query_pos].strip()
            new_input = content[last_query_pos + len("QUERY>>> ") :].strip()
        else:
            history_part = content.strip()
            new_input = ""

        # If history part is empty, flag for reset
        reset = not history_part

        return new_input if new_input else None, reset

    def run(self):
        while True:
            self.save_history()
            user_input, reset = self.get_user_input_from_vim()
            if reset:
                self.messages = [{"role": "system", "content": self.system_prompt}]
                print("Chat history nuked.")
            if user_input is None:
                user_input = "exit"
                no_input_exit = True
            else:
                no_input_exit = False
                print(
                    "QUERY>>> " + user_input
                )  # Echo the input from Vim so it shows in terminal, dammit

            if user_input.lower() == "exit":
                if not (
                    len(self.messages) > 1 and no_input_exit
                ):  # Don't print exit message if no input exit after first
                    print(
                        "Exiting. Go hack on the kernel or something useful, you slacker."
                    )
                # Clean up the temp file, because /tmp isn't your trash bin
                self.cleanup_history_file()
                break

            # Add user message
            self.messages.append({"role": "user", "content": user_input})

            try:
                self.stream_response()
            except Exception as e:
                print(f"Error: {str(e)}. Sort your dependencies or network, dammit.")

    def stream_response(self, show_loader=True, use_color=True):
        color_prefix = self.ai_color if use_color else ""
        color_reset = self.reset_color if use_color else ""
        self.stop_loader = False
        loader_thread = None

        if show_loader:

            def loader():
                i = 0
                while not self.stop_loader:
                    dots = "." * (i % 4)
                    print(
                        f"\r{color_prefix}{dots:<4}{color_reset}",
                        end="",
                        flush=True,
                    )
                    i += 1
                    time.sleep(0.1)

            loader_thread = threading.Thread(target=loader)
            loader_thread.start()

        ai_reply = ""
        first_chunk = True

        try:
            stream = self.client.chat.completions.create(  # type: ignore[arg-type]
                model=self.model,
                messages=self.messages,  # type: ignore[arg-type]
                stream=True,
            )

            for chunk in stream:
                if first_chunk:
                    if loader_thread:
                        self.stop_loader = True
                        loader_thread.join()
                        print("\r    \r", end="", flush=True)
                    if use_color:
                        print(color_prefix, end="", flush=True)
                    first_chunk = False

                if chunk.choices[0].delta.content is not None:
                    content = chunk.choices[0].delta.content
                    ai_reply += content
                    print(content, end="", flush=True)
                    time.sleep(0.02)

            if first_chunk:
                # No content arrived; still print a header so the user isn't confused.
                if loader_thread:
                    self.stop_loader = True
                    loader_thread.join()
                    print("\r    \r", end="", flush=True)
                if use_color:
                    print(color_prefix, end="", flush=True)

            if use_color:
                print(color_reset, end="")
            print()
        finally:
            self.stop_loader = True
            if loader_thread and loader_thread.is_alive():
                loader_thread.join()

        self.messages.append({"role": "assistant", "content": ai_reply.strip()})
        return ai_reply.strip()


def start_loader(color_prefix=""):
    if not sys.stdout.isatty():
        return None, None

    stop_event = threading.Event()
    color_reset = COLOR_RESET if color_prefix else ""

    def loader():
        i = 0
        while not stop_event.is_set():
            dots = "." * (i % 4)
            print(f"\r{color_prefix}{dots:<4}{color_reset}", end="", flush=True)
            i += 1
            time.sleep(0.1)

    thread = threading.Thread(target=loader)
    thread.start()
    return stop_event, thread


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Codex-style terminal assistant"
    )
    parser.add_argument(
        "scope_or_prompt",
        nargs="?",
        help="Optional file/directory scope or the beginning of the prompt",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Additional prompt words",
    )
    return parser.parse_args(argv)


def strip_code_fence(raw_response):
    text = (raw_response or "").strip()
    if text.startswith("```"):
        fence_break = text.find("\n")
        if fence_break == -1:
            return ""
        text = text[fence_break + 1 :]
        text = text.rsplit("```", 1)[0]
    return text.replace("\r\n", "\n").strip("\n")


def add_line_numbers_to_diff(diff_lines):
    numbered = []
    old_no = new_no = None
    header_pattern = re.compile(r"^@@ -(?P<old>\d+)(?:,(?P<old_count>\d+))? \+(?P<new>\d+)(?:,(?P<new_count>\d+))? @@")

    colorize = sys.stdout.isatty()

    for line in diff_lines:
        if line.startswith("@@"):
            match = header_pattern.match(line)
            if match:
                old_no = int(match.group("old"))
                new_no = int(match.group("new"))
            numbered.append(line)
            continue

        if line.startswith("--- ") or line.startswith("+++ ") or line.startswith("diff "):
            numbered.append(line)
            continue

        if not line or line[0] not in {" ", "-", "+"}:
            numbered.append(line)
            continue

        prefix = line[:1]
        old_label = new_label = ""

        if prefix == "-":
            if old_no is None:
                old_no = 1
            old_label = str(old_no)
            old_no += 1
        elif prefix == "+":
            if new_no is None:
                new_no = 1
            new_label = str(new_no)
            new_no += 1
        elif prefix == " ":
            if old_no is None:
                old_no = 1
            if new_no is None:
                new_no = 1
            old_label = str(old_no)
            new_label = str(new_no)
            old_no += 1
            new_no += 1

        formatted = f"{old_label:>6} {new_label:>6} {line}"

        if colorize:
            if prefix == "+":
                formatted = f"{COLOR_ADD}{formatted}{COLOR_RESET}"
            elif prefix == "-":
                formatted = f"{COLOR_REMOVE}{formatted}{COLOR_RESET}"
            else:
                formatted = f"{COLOR_CONTEXT}{formatted}{COLOR_RESET}"

        numbered.append(formatted)

    return "\n".join(numbered)


def _coalesce_responses_text(response: Any) -> str:
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
        content_chunks: list[str] = []
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
            parts = [text for item in obj if (text := _from_output(item))]
            return "".join(parts)

        if isinstance(obj, str):
            return obj

        return ""

    return _from_output(data).strip()


def _make_user_message(text: str) -> Dict[str, Any]:
    return {"role": "user", "content": [{"type": "input_text", "text": text}]}


def _make_assistant_message(text: str) -> Dict[str, Any]:
    return {"role": "assistant", "content": [{"type": "output_text", "text": text}]}


def _make_tool_result_message(call_id: str, text: str) -> Dict[str, Any]:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": text,
    }


def _to_plain_data(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, dict):
        return {key: _to_plain_data(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_plain_data(value) for value in obj]
    if hasattr(obj, "model_dump"):
        return _to_plain_data(obj.model_dump())
    if hasattr(obj, "dict"):
        return _to_plain_data(obj.dict())
    try:
        iterable = iter(obj)  # type: ignore[arg-type]
    except TypeError:
        return str(obj)
    else:
        return [_to_plain_data(item) for item in iterable]


def _convert_response_item(obj: Any) -> Dict[str, Any]:
    data = _to_plain_data(obj)
    if isinstance(data, dict):
        return data
    raise TypeError(f"Unable to convert response item of type {type(obj)!r} to dict")


def _sanitize_reasoning_item(payload: Dict[str, Any]) -> Dict[str, Any]:
    allowed_keys = {"type", "id", "content", "summary"}
    sanitized: Dict[str, Any] = {}
    for key in allowed_keys:
        if key in payload and payload[key] is not None:
            sanitized[key] = payload[key]
    sanitized.setdefault("type", "reasoning")
    return sanitized


def _make_tool_call_item(
    *,
    call_id: str,
    tool_name: str,
    arguments: Any,
    raw_id: Any = None,
    reasoning_id: str | None = None,
) -> Dict[str, Any]:
    serialized_arguments = arguments if isinstance(arguments, str) else json.dumps(arguments or {})
    item: Dict[str, Any] = {
        "type": "function_call",
        "call_id": call_id,
        "name": tool_name,
        "arguments": serialized_arguments,
    }
    if raw_id is not None:
        item["id"] = str(raw_id)
    if reasoning_id:
        item["reasoning_id"] = reasoning_id
    return item


def _detect_generated_files(message: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        r"(?:save|write|create|add|generate|produce)[^\n]{0,160}?\b(?:as|to|in)\s+`?([A-Za-z0-9._\-/]+)`?(?::)?",
        re.IGNORECASE,
    )
    lines = message.splitlines()
    i = 0
    results: list[tuple[str, str]] = []
    while i < len(lines):
        match = pattern.search(lines[i])
        if not match:
            i += 1
            continue

        filename = match.group(1).strip().rstrip(':').strip()
        j = i + 1
        while j < len(lines) and not lines[j].startswith("```"):
            j += 1
        if j >= len(lines):
            i += 1
            continue
        fence_language = lines[j]
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


def _review_and_apply_file_update(
    base_root: Path,
    default_root: Path,
    filename: str,
    content: str,
    *,
    auto_apply: bool = False,
) -> str:
    path = Path(filename)
    if not path.is_absolute():
        path = (default_root / path).resolve()
    else:
        path = path.resolve()

    try:
        relative = path.relative_to(base_root)
    except ValueError:
        print(f"[skip] refusing to modify outside project root: {path}")
        return "skipped_out_of_scope"

    try:
        old_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        old_text = ""
    except Exception as exc:
        print(f"[skip] failed to read {relative}: {exc}")
        return f"error: failed to read {relative}: {exc}"

    diff_lines = list(
        difflib.unified_diff(
            old_text.splitlines(),
            content.splitlines(),
            fromfile=str(relative),
            tofile=f"{relative} (proposed)",
            lineterm="",
        )
    )

    if not diff_lines:
        print(f"[skip] {relative}: no changes detected")
        return "no_change"

    print(add_line_numbers_to_diff(diff_lines))

    if auto_apply:
        print(f"[auto] applying changes to {relative}")
        normalized = "y"
    else:
        try:
            confirmation_raw = input(f"Apply changes to {relative}? [y/N]: ").strip().lower()
        except KeyboardInterrupt:
            print("\nInterrupted while awaiting confirmation.")
            raise
        normalized = re.sub(r"[^a-z]", "", confirmation_raw)

    positive = {
        "y",
        "yes",
        "ok",
        "okay",
        "sure",
        "apply",
        "add",
        "addit",
        "create",
        "commit",
        "confirm",
        "doit",
        "do",
        "write",
        "writeit",
        "save",
    }

    if normalized not in positive:
        print(f"[skip] {relative}")
        return "user_rejected"

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content + ("\n" if not content.endswith("\n") else ""), encoding="utf-8")
        os.chmod(path, 0o644)
        print(f"[applied] {relative}")
    except Exception as exc:
        print(f"[error] failed to write {relative}: {exc}")
        return f"error: failed to write {relative}: {exc}"

    return "applied"


def _instruction_implies_write(text: str) -> bool:
    normalized = text.lower()
    return bool(
        re.search(
            r"\b(write|create|add|generate|produce|save|append|commit|apply|patch|update|make|build|draft|add it|addit|writeit)\b",
            normalized,
        )
    )


def _handle_tool_call(
    tool_name: str,
    arguments: Any,
    *,
    base_root: Path,
    default_root: Path,
    config: Dict[str, Any],
    plan_state: Dict[str, Any],
    latest_instruction: str,
) -> tuple[str, bool]:
    try:
        if isinstance(arguments, str):
            args = json.loads(arguments) if arguments else {}
        elif isinstance(arguments, dict):
            args = arguments
        else:
            args = {}
    except json.JSONDecodeError as exc:
        print(f"[tool-call] {tool_name}: failed to decode arguments: {exc}")
        return f"error: invalid arguments JSON ({exc})", False

    mutated = False
    if tool_name in {"write", "write_file"}:
        print(f"[tool-call] {tool_name}: parsed args={args}")

    if tool_name == "read_file":
        path_arg = args.get("path")
        if not path_arg:
            return "error: missing path", False
        path = Path(path_arg)
        if not path.is_absolute():
            path = (default_root / path).resolve()
        else:
            path = path.resolve()
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
        print(preview)
        return preview, False

    if tool_name in {"write", "write_file"}:
        path_arg = args.get("filePath") or args.get("path")
        contents = args.get("content")
        if contents is None:
            contents = args.get("contents")
        if not path_arg or contents is None:
            return "error: missing file path or contents", False
        auto_apply = _instruction_implies_write(latest_instruction)
        status = _review_and_apply_file_update(
            base_root,
            default_root,
            path_arg,
            contents,
            auto_apply=auto_apply,
        )
        mutated = status == "applied"
        if status == "applied":
            try:
                target_path = Path(path_arg).expanduser()
                if not target_path.is_absolute():
                    target_path = (default_root / target_path).resolve()
                else:
                    target_path = target_path.resolve()
                relative = target_path.relative_to(base_root)
                status_message = f"success: wrote {relative}"
            except Exception:
                status_message = "success: wrote file"
            print(f"[tool-call] {tool_name}: wrote file -> {status_message}")
            return status_message, mutated
        if status == "no_change":
            print(f"[tool-call] {tool_name}: no change for {path_arg}")
            return "no change", mutated
        print(f"[tool-call] {tool_name}: status={status}")
        return status, mutated

    if tool_name == "apply_patch":
        patch_text = args.get("patch") or args.get("input")
        if not patch_text:
            return "error: missing patch", False
        print("# apply_patch proposal\n" + patch_text)
        try:
            confirmation = input("Apply patch? [y/N]: ").strip().lower()
        except KeyboardInterrupt:
            print("\nInterrupted while awaiting confirmation.")
            raise
        if confirmation not in {"y", "yes"}:
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
                print(proc.stdout)
            if proc.stderr:
                print(proc.stderr)
            return f"error: patch failed (status {proc.returncode})", False
        if proc.stdout:
            print(proc.stdout)
        return "applied", True

    if tool_name == "shell":
        command = args.get("command")
        if isinstance(command, str):
            command_str = command
        elif isinstance(command, list):
            command_str = " ".join(shlex.quote(str(part)) for part in command)
        else:
            return "error: invalid command; expected string or list", False

        workdir_arg = args.get("workdir")
        if workdir_arg:
            workdir = Path(workdir_arg).expanduser()
            if not workdir.is_absolute():
                workdir = (default_root / workdir).resolve()
        else:
            workdir = default_root

        try:
            workdir.relative_to(base_root)
        except ValueError:
            return f"error: workdir outside project root ({workdir})", False

        settings = config.get("bash_settings", {})
        timeout_seconds = int(settings.get("max_seconds", 15) or 15)
        max_output_bytes = int(settings.get("max_output_bytes", 20000) or 20000)
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
            print(formatted)
            return formatted, False
        except CommandRejected as exc:
            message = f"command rejected: {exc}"
            print(f"[shell] {message}")
            return message, False

    if tool_name == "update_plan":
        plan = (args.get("plan") or "").strip()
        explanation = (args.get("explanation") or "").strip()
        plan_state["plan"] = plan
        if plan:
            print("# Updated Plan\n" + plan)
        if explanation:
            print("# Plan Explanation\n" + explanation)
        response = "plan updated"
        if explanation:
            response += f"; notes: {explanation}"
        return response, False

    print(f"[tool-call] unknown tool '{tool_name}' with args={args}")
    return f"error: unknown tool '{tool_name}'", False


def run_codex_edit(
    path_str: str,
    instruction: str,
    model: str | None = None,
    config: Dict[str, Any] | None = None,
    baseline_text: str | None = None,
):
    target_path = Path(path_str).expanduser()
    if target_path.is_dir():
        print(f"{target_path} is a directory, not a file. Try harder.")
        return 1

    if target_path.exists():
        try:
            current_text = target_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"{target_path} isn't UTF-8 text. I'm not hex-editing that for you.")
            return 1
        except OSError as exc:
            print(f"Couldn't read {target_path}: {exc}")
            return 1
    else:
        current_text = ""

    base_text = current_text if baseline_text is None else baseline_text

    if baseline_text is not None and current_text != baseline_text:
        print(
            "File changed on disk since the edit session began. Showing diff against"
            " the original snapshot.",
            file=sys.stderr,
        )

    effective_model = resolve_model("edit", config, model)
    api_key_value = resolve_api_key(config=config)
    client = openai.OpenAI(api_key=api_key_value)
    system_message = (
        "You rewrite files. Return only the complete updated file content. "
        "No explanations, no code fences, no commentary."
    )
    user_message = (
        f"File: {target_path}\n"
        "Instruction:\n"
        f"{instruction}\n\n"
        "Original file contents:\n"
        f"{base_text}"
    )

    stop_event, loader_thread = start_loader()
    content = ""

    try:
        if _is_responses_model(effective_model):
            response = client.responses.create(  # type: ignore[arg-type]
                model=effective_model,
                input=f"{system_message}\n\n{user_message}",
            )
            content = _coalesce_responses_text(response)
        else:
            chat_response = client.chat.completions.create(  # type: ignore[arg-type]
                model=effective_model,
                messages=[  # type: ignore[arg-type]
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message},
                ],
            )
            if not chat_response.choices:
                content = ""
            else:
                choice = chat_response.choices[0]
                content_obj = getattr(choice.message, "content", None)
                content = content_obj if isinstance(content_obj, str) else ""
    except Exception as exc:
        print(f"Error: {exc}. The API tripped over itself.")
        return 1
    finally:
        if stop_event and loader_thread:
            stop_event.set()
            loader_thread.join()
            print("\r    \r", end="", flush=True)
        elif stop_event:
            stop_event.set()

    if not content:
        print("Model returned no content. Aborting.")
        return 1

    proposed_text = strip_code_fence(content)

    if proposed_text == "":
        print("Model returned empty content. Not touching your file.")
        return 1

    if proposed_text == current_text:
        print("Model produced identical content. Nothing to do.")
        return 0

    status = _review_and_apply_file_update(
        base_root=Path.cwd().resolve(),
        default_root=target_path.parent,
        filename=str(target_path),
        content=proposed_text,
        auto_apply=_instruction_implies_write(instruction),
    )

    if status == "user_rejected":
        try:
            extra_context = input("add_context >>> ").strip()
        except KeyboardInterrupt:
            print("\nInterrupted. Exiting without changes.")
            raise
        if extra_context:
            combined_instruction = (
                f"{instruction}\n\nAdditional context provided after review:\n{extra_context}"
            )
            return run_codex_edit(
                path_str,
                combined_instruction,
                model=model,
                config=config,
                baseline_text=base_text,
            )
        return 0

    if status.startswith("error"):
        return 1

    return 0


def _resolve_scope(scope: str | None, repo_root: Path) -> tuple[Path, Path, str]:
    if not scope:
        return repo_root, repo_root, "repository root"

    candidate = Path(scope).expanduser()
    if not candidate.is_absolute():
        candidate = (repo_root / candidate).resolve()
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError("Scope path must be inside the repository") from exc

    if not candidate.exists():
        raise FileNotFoundError(candidate)

    if candidate.is_dir():
        label = str(candidate.relative_to(repo_root)) or "."
        return candidate, candidate, label

    label = str(candidate.relative_to(repo_root))
    return candidate.parent, candidate.parent, label


def run_codex_conversation(prompt: str, scope: str | None, config: Dict[str, Any]) -> int:
    raw_prompt = (prompt or "").strip()
    if not raw_prompt:
        print("Provide a question or instruction.")
        return 1

    repo_root = Path.cwd().resolve()
    try:
        _, scope_root, scope_label = _resolve_scope(scope, repo_root)
    except FileNotFoundError as exc:
        print(f"Scope path {exc} does not exist.", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    collected = collect_context(scope_root)
    display_text = format_context_for_display(collected)
    prompt_context = format_context_for_prompt(collected)

    print("# Collected Context")
    print(display_text)

    model = resolve_model("bash", config)
    api_key_value = resolve_api_key(config=config)
    client = openai.OpenAI(api_key=api_key_value)

    scope_sentence = (
        "Focus on the entire repository." if scope_label == "repository root" else f"Scope: {scope_label}."
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
    pending_user_message: str | None = "\n".join(
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
    pending_context_update: str | None = None
    context_dirty = False

    while True:
        if context_dirty:
            collected = collect_context(scope_root)
            prompt_context = format_context_for_prompt(collected)
            pending_context_update = prompt_context
            context_dirty = False

        if pending_context_update:
            conversation_items.append(
                _make_user_message("Updated repository snapshot:\n" + pending_context_update)
            )
            pending_context_update = None

        if pending_user_message:
            conversation_items.append(_make_user_message(pending_user_message))
            pending_user_message = None

        try:
            conversation_payload: Any = conversation_items
            tools_payload: Any = TOOL_DEFINITIONS
            response = client.responses.create(
                model=model,
                instructions=system_prompt,
                input=conversation_payload,
                tools=tools_payload,
                tool_choice="auto",
            )
        except KeyboardInterrupt:
            print("\nInterrupted by user.")
            return 130
        except Exception as exc:  # pragma: no cover - network issues
            print(f"Error: {exc}")
            return 1

        tool_call_handled = False
        assistant_messages: list[str] = []
        pending_reasoning_queue: list[Dict[str, Any]] = []

        for item in getattr(response, "output", []) or []:
            item_type = getattr(item, "type", "")
            debug_payload = {
                "type": item_type,
                "id": getattr(item, "id", None),
                "call_id": getattr(item, "call_id", None),
                "name": getattr(item, "name", None),
            }
            reasoning_ref = getattr(item, "reasoning_id", None)
            if reasoning_ref:
                debug_payload["reasoning_id"] = reasoning_ref
            try:
                print("[debug] response item " + json.dumps(debug_payload, default=str))
            except Exception:
                print(f"[debug] response item type={item_type}")

            if item_type == "message":
                if pending_reasoning_queue:
                    print(f"[debug] flushing {len(pending_reasoning_queue)} reasoning items before message")
                    while pending_reasoning_queue:
                        conversation_items.append(pending_reasoning_queue.pop(0))
                text_parts: list[str] = []
                for block in getattr(item, "content", []) or []:
                    if getattr(block, "type", "").endswith("text"):
                        text_parts.append(getattr(block, "text", ""))
                text = "".join(text_parts).strip()
                if text:
                    assistant_messages.append(text)
                    conversation_items.append(_make_assistant_message(text))
            elif item_type in {"tool_call", "function_call"}:
                item_payload = _convert_response_item(item)
                try:
                    print("[debug] function_call payload " + json.dumps(item_payload, indent=2))
                except Exception:
                    print(f"[debug] function_call payload keys={list(item_payload.keys())}")
                raw_item_id = getattr(item, "id", None)
                raw_call_id = getattr(item, "call_id", None) or raw_item_id
                tool_name = getattr(item, "name", "")
                call_id = str(raw_call_id or f"tool-{tool_name}")
                arguments_payload = item_payload.get("arguments", {})
                reasoning_id = item_payload.get("reasoning_id")
                selected_reasoning = None
                if reasoning_id:
                    for idx, pending in enumerate(pending_reasoning_queue):
                        if pending.get("id") == reasoning_id:
                            selected_reasoning = pending_reasoning_queue.pop(idx)
                            print(f"[debug] attaching reasoning {reasoning_id} to call {call_id}")
                            break
                if selected_reasoning is None and pending_reasoning_queue:
                    selected_reasoning = pending_reasoning_queue.pop(0)
                    print(
                        f"[debug] attaching inferred reasoning {selected_reasoning.get('id')} to call {call_id}"
                    )
                if selected_reasoning:
                    conversation_items.append(selected_reasoning)
                conversation_items.append(
                    _make_tool_call_item(
                        call_id=call_id,
                        tool_name=tool_name,
                        arguments=arguments_payload,
                        raw_id=raw_item_id,
                        reasoning_id=reasoning_id,
                    )
                )
                result_text, mutated = _handle_tool_call(
                    tool_name,
                    arguments_payload,
                    base_root=repo_root,
                    default_root=scope_root if scope else repo_root,
                    config=config,
                    plan_state=plan_state,
                    latest_instruction=latest_instruction,
                )
                conversation_items.append(_make_tool_result_message(call_id, result_text))
                if mutated:
                    context_dirty = True
                tool_call_handled = True

            elif item_type == "custom_tool_call":
                tool_name = getattr(item, "name", "")
                print(f"[tool-call] unsupported custom tool '{tool_name}' requested; ignoring")
                tool_call_handled = True

            elif item_type == "reasoning":
                try:
                    reasoning_payload = _convert_response_item(item)
                except TypeError as exc:
                    print(f"[tool-call] failed to serialize reasoning item: {exc}")
                else:
                    sanitized = _sanitize_reasoning_item(reasoning_payload)
                    pending_reasoning_queue.append(sanitized)
                    print(f"[debug] queued reasoning {sanitized.get('id')}")
                summary = getattr(item, "summary", None)
                if summary:
                    reasoning_text = getattr(summary, "text", "") if hasattr(summary, "text") else summary
                    if reasoning_text:
                        print(f"# Reasoning\n{reasoning_text}\n")

        if pending_reasoning_queue and not tool_call_handled:
            print(f"[debug] flushing {len(pending_reasoning_queue)} remaining reasoning items post-loop")
            while pending_reasoning_queue:
                conversation_items.append(pending_reasoning_queue.pop(0))

        if tool_call_handled:
            continue

        manual_mutation = False
        if assistant_messages:
            for message in assistant_messages:
                print(message)
                for filename, content in _detect_generated_files(message):
                    status = _review_and_apply_file_update(
                        base_root=repo_root,
                        default_root=scope_root if scope else repo_root,
                        filename=filename,
                        content=content,
                        auto_apply=_instruction_implies_write(latest_instruction),
                    )
                    if status == "applied":
                        manual_mutation = True
                    elif status.startswith("error"):
                        print(status)
        if manual_mutation:
            context_dirty = True

        if assistant_messages and not manual_mutation:
            maybe_creation_claim = any(
                re.search(r"\b(created|saved|written|added|generated)\b", msg, re.IGNORECASE)
                for msg in assistant_messages
            )
            if maybe_creation_claim:
                pending_user_message = (
                    "It appears no files changed. Please call the `write` tool (alias: `write_file`) with the full contents so the file can be created."
                )
                continue

        try:
            follow_up = input("follow_up >>> ").strip()
        except KeyboardInterrupt:
            print("\nInterrupted by user.")
            return 130

        if not follow_up:
            return 0

        latest_instruction = follow_up
        pending_user_message = (
            "Follow-up instruction:\n"
            + follow_up
            + "\n\nReminder: use the `write` tool (or `write_file`) with full file contents when files must change."
        )


def main(argv=None):
    arg_list = list(sys.argv[1:] if argv is None else argv)

    primary_rc = _handle_primary_flags(arg_list)
    if primary_rc is not None:
        return primary_rc

    config = load_config()

    args = parse_args(arg_list)

    scope_candidate = args.scope_or_prompt
    prompt_components = list(args.prompt)
    scope_arg: str | None = None

    if scope_candidate:
        candidate_path = Path(scope_candidate).expanduser()
        if candidate_path.exists():
            scope_arg = str(candidate_path)
            if candidate_path.is_file():
                prompt_text = " ".join(prompt_components).strip()
                if not prompt_text:
                    print("Provide an instruction after the file path.")
                    return 1
                return run_codex_edit(scope_arg, prompt_text, config=config)
            else:
                # directory scope
                prompt_text = " ".join(prompt_components).strip()
                if not prompt_text:
                    print("Provide a question or instruction.")
                    return 1
                return run_codex_conversation(prompt_text, scope_arg, config)
        else:
            prompt_components.insert(0, scope_candidate)

    prompt_text = " ".join(prompt_components).strip()
    if not prompt_text:
        _print_help()
        return 1

    return run_codex_conversation(prompt_text, scope_arg, config)

    # Unreachable due to early returns, but keep explicit guard.
    return 0


if __name__ == "__main__":
    try:
        exit_code = main(sys.argv[1:])
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(130)
    else:
        sys.exit(exit_code)
