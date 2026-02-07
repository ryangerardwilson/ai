from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import fnmatch
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
    {
        "type": "function",
        "name": "unit_test_coverage",
        "description": "Run Python pytest with coverage (term-missing report) and return the formatted output.",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Optional test target path or pattern",
                },
                "extraArgs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional pytest arguments",
                },
                "timeout_ms": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional timeout in milliseconds",
                },
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "glob",
        "description": "List repository paths matching a glob pattern (relative to the project root unless cwd provided).",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g., **/*.py)",
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional directory to treat as current working directory",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Maximum number of matches to return (default 200)",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "type": "function",
        "name": "search_content",
        "description": "Search file contents using a regex (prefer this over shell grep). Returns path:line:text snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression to search for",
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional directory within the repo to search",
                },
                "include": {
                    "type": ["string", "array"],
                    "items": {"type": "string"},
                    "description": "Glob pattern(s) to include",
                },
                "exclude": {
                    "type": ["string", "array"],
                    "items": {"type": "string"},
                    "description": "Glob pattern(s) to exclude",
                },
                "maxResults": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Maximum number of matches to return (default 200)",
                },
                "caseSensitive": {
                    "type": "boolean",
                    "description": "Set false for case-insensitive search",
                },
            },
            "required": ["pattern"],
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

    if tool_name == "unit_test_coverage":
        return run_unit_test_coverage(args, runtime)

    if tool_name == "glob":
        return run_glob_search(args, runtime)

    if tool_name == "search_content":
        return run_search_content(args, runtime)

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


def run_unit_test_coverage(
    args: Dict[str, Any], runtime: ToolRuntime
) -> tuple[str, bool]:
    target = args.get("target")
    if target is not None and not isinstance(target, str):
        return "error: target must be a string", False

    extra_args = args.get("extraArgs")
    if extra_args is None:
        extra_args = args.get("extra_args")
    if extra_args is not None:
        if not isinstance(extra_args, list) or not all(
            isinstance(item, str) for item in extra_args
        ):
            return "error: extraArgs must be a list of strings", False

    command_parts = ["pytest", "--cov", "--cov-report=term-missing"]
    if target:
        cleaned_target = target.strip()
        if cleaned_target:
            command_parts.append(cleaned_target)

    if extra_args:
        command_parts.extend(extra_args)

    command_str = " ".join(shlex.quote(part) for part in command_parts)

    timeout_ms = args.get("timeout_ms")
    timeout_seconds = 120
    if timeout_ms is not None:
        try:
            timeout_seconds = max(1, int(timeout_ms) // 1000)
        except Exception:
            return "error: invalid timeout_ms", False

    try:
        result = run_sandboxed_bash(
            command_str,
            cwd=runtime.default_root,
            scope_root=runtime.base_root,
            timeout=timeout_seconds,
            max_output_bytes=50000,
        )
    except CommandRejected as exc:
        message = f"command rejected: {exc}"
        runtime.renderer.display_error(message)
        return message, False
    except Exception as exc:
        message = f"error: failed to run pytest coverage: {exc}"
        runtime.renderer.display_error(message)
        return message, False

    formatted = format_command_result(result)
    rendered_parts = [f"$ {command_str}"]
    if formatted.strip():
        rendered_parts.append(formatted)
    else:
        rendered_parts.append("(no output)")
    rendered = "\n\n".join(rendered_parts)
    runtime.renderer.display_shell_output(rendered)
    return rendered, False


def run_glob_search(args: Dict[str, Any], runtime: ToolRuntime) -> tuple[str, bool]:
    pattern = args.get("pattern")
    if not isinstance(pattern, str) or not pattern.strip():
        return "error: pattern must be a non-empty string", False
    pattern_str = pattern.strip()

    limit_value = args.get("limit")
    if limit_value is None:
        limit = 200
    else:
        try:
            limit = int(limit_value)
        except (TypeError, ValueError):
            return "error: limit must be an integer", False
        if limit < 1:
            return "error: limit must be at least 1", False
        if limit > 1000:
            limit = 1000

    cwd_arg = args.get("cwd")
    if cwd_arg is not None:
        if not isinstance(cwd_arg, str) or not cwd_arg.strip():
            return "error: cwd must be a non-empty string", False
        cwd_path = Path(cwd_arg).expanduser()
        if not cwd_path.is_absolute():
            cwd_path = (runtime.default_root / cwd_path).resolve()
        else:
            cwd_path = cwd_path.resolve()
        try:
            cwd_path.relative_to(runtime.base_root)
        except ValueError:
            return f"error: cwd outside project root ({cwd_path})", False
        search_root = cwd_path
    else:
        search_root = runtime.default_root

    if not search_root.exists():
        return f"error: cwd does not exist ({search_root})", False

    matches: List[Path] = []
    for candidate in search_root.glob(pattern_str):
        candidate_path = candidate.resolve()
        try:
            candidate_path.relative_to(runtime.base_root)
        except ValueError:
            continue
        matches.append(candidate_path)
        if len(matches) >= limit:
            break

    if not matches:
        message = f"Glob pattern '{pattern_str}' returned no matches."
        runtime.renderer.display_info(message)
        return message, False

    relative_matches = [
        str(path.relative_to(runtime.base_root))
        for path in matches
    ]
    header = f"Glob matches for '{pattern_str}' (showing {len(relative_matches)}):"
    rendered = "\n".join([header, *relative_matches])
    runtime.renderer.display_info(rendered)
    return rendered, False


def run_search_content(
    args: Dict[str, Any], runtime: ToolRuntime
) -> tuple[str, bool]:
    pattern_raw = args.get("pattern")
    if not isinstance(pattern_raw, str) or not pattern_raw.strip():
        return "error: pattern must be a non-empty string", False
    pattern = pattern_raw.strip()

    case_sensitive = args.get("caseSensitive")
    if case_sensitive is None:
        case_sensitive_flag = True
    elif isinstance(case_sensitive, bool):
        case_sensitive_flag = case_sensitive
    else:
        return "error: caseSensitive must be a boolean", False

    max_results_arg = args.get("maxResults")
    if max_results_arg is None:
        max_results = 200
    else:
        try:
            max_results = int(max_results_arg)
        except (TypeError, ValueError):
            return "error: maxResults must be an integer", False
        if max_results < 1:
            return "error: maxResults must be at least 1", False
        if max_results > 1000:
            max_results = 1000

    def _normalize_patterns(value: Any, key: str) -> tuple[List[str], Optional[str]]:
        if value is None:
            return [], None
        if isinstance(value, str):
            patterns = [value]
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            patterns = list(value)
        else:
            return [], f"error: {key} must be a string or list of strings"
        normalized = [item.strip() for item in patterns if item and item.strip()]
        return normalized, None

    include_patterns, include_error = _normalize_patterns(args.get("include"), "include")
    if include_error:
        return include_error, False

    exclude_patterns, exclude_error = _normalize_patterns(args.get("exclude"), "exclude")
    if exclude_error:
        return exclude_error, False

    cwd_arg = args.get("cwd")
    if cwd_arg is not None:
        if not isinstance(cwd_arg, str) or not cwd_arg.strip():
            return "error: cwd must be a non-empty string", False
        cwd_path = Path(cwd_arg).expanduser()
        if not cwd_path.is_absolute():
            search_root = (runtime.default_root / cwd_path).resolve()
        else:
            search_root = cwd_path.resolve()
        try:
            search_root.relative_to(runtime.base_root)
        except ValueError:
            return f"error: cwd outside project root ({search_root})", False
    else:
        search_root = runtime.default_root

    if not search_root.exists():
        return f"error: cwd does not exist ({search_root})", False

    matches: List[Dict[str, Any]] = []
    truncated = False

    rg_used = False
    command_result = None
    command_error: Optional[str] = None

    command_parts: List[str] = [
        "rg",
        "--json",
        "--line-number",
        "--color",
        "never",
    ]
    if not case_sensitive_flag:
        command_parts.append("-i")
    for pattern_text in include_patterns:
        command_parts.extend(["-g", pattern_text])
    for pattern_text in exclude_patterns:
        command_parts.extend(["-g", f"!{pattern_text}"])
    command_parts.extend(["-m", str(max_results)])
    command_parts.append(pattern)
    command_parts.append(".")

    command_str = " ".join(shlex.quote(part) for part in command_parts)

    try:
        command_result = run_sandboxed_bash(
            command_str,
            cwd=search_root,
            scope_root=runtime.base_root,
            timeout=30,
            max_output_bytes=60000,
        )
        rg_used = True
    except CommandRejected:
        command_result = None
    except Exception as exc:  # pragma: no cover - defensive
        command_result = None
        command_error = f"rg invocation failed: {exc}"

    if command_result is not None:
        if command_result.exit_code in {0, 1}:  # 1 means no matches
            stdout = command_result.stdout.strip()
            if stdout:
                for line in stdout.splitlines():
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("type") != "match":
                        continue
                    data = payload.get("data", {})
                    path_text = (
                        data.get("path", {}).get("text")
                        if isinstance(data.get("path"), dict)
                        else None
                    )
                    if not path_text:
                        continue
                    path_obj = (search_root / path_text).resolve()
                    try:
                        relative = path_obj.relative_to(runtime.base_root)
                    except ValueError:
                        continue
                    line_number = data.get("line_number")
                    if not isinstance(line_number, int):
                        continue
                    line_text = (
                        data.get("lines", {}).get("text")
                        if isinstance(data.get("lines"), dict)
                        else ""
                    )
                    line_text = (line_text or "").rstrip("\n")
                    matches.append(
                        {
                            "path": str(relative),
                            "line": line_number,
                            "text": line_text,
                        }
                    )
                    if len(matches) >= max_results:
                        truncated = True
                        break
            if matches:
                pass
            elif command_result.exit_code == 1:
                message = (
                    f"Search pattern '{pattern}' returned no matches in {search_root.relative_to(runtime.base_root)}"
                    if search_root != runtime.base_root
                    else f"Search pattern '{pattern}' returned no matches."
                )
                runtime.renderer.display_info(message)
                return message, False
        else:
            command_error = command_result.stderr.strip() or command_result.stdout.strip()

    if not matches and command_error:
        runtime.renderer.display_info(
            "rg unavailable or failed; falling back to Python search"
        )

    if not matches and not command_error and command_result is not None and rg_used:
        # rg ran successfully but produced no matches (already handled) or stdout empty
        if command_result.exit_code == 0:
            message = (
                f"Search pattern '{pattern}' returned no matches."
            )
            runtime.renderer.display_info(message)
            return message, False

    if not matches:
        # fallback search in Python when rg failed or produced nothing with error
        flags = re.MULTILINE
        if not case_sensitive_flag:
            flags |= re.IGNORECASE
        try:
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            return f"error: invalid regex ({exc})", False

        def within_patterns(path_str: str) -> bool:
            if include_patterns and not any(
                fnmatch.fnmatch(path_str, pat) for pat in include_patterns
            ):
                return False
            if exclude_patterns and any(
                fnmatch.fnmatch(path_str, pat) for pat in exclude_patterns
            ):
                return False
            return True

        for file_path in search_root.rglob("*"):
            if not file_path.is_file():
                continue
            try:
                relative = file_path.relative_to(runtime.base_root)
            except ValueError:
                continue
            relative_str = str(relative)
            if not within_patterns(relative_str):
                continue
            try:
                with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if compiled.search(line):
                            matches.append(
                                {
                                    "path": relative_str,
                                    "line": line_number,
                                    "text": line.rstrip("\n"),
                                }
                            )
                            if len(matches) >= max_results:
                                truncated = True
                                break
                if len(matches) >= max_results:
                    break
            except OSError:
                continue

        if not matches:
            message = (
                f"Search pattern '{pattern}' returned no matches."
            )
            runtime.renderer.display_info(message)
            return message, False

    if len(matches) > max_results:
        matches = matches[:max_results]
        truncated = True

    match_count = len(matches)
    count_label = "match" if match_count == 1 else "matches"
    header = f"Search results for '{pattern}' – {match_count} {count_label}"
    if truncated:
        header += f" (truncated at {max_results})"
    if search_root != runtime.base_root:
        header += f" in {search_root.relative_to(runtime.base_root)}"

    lines = [header]
    for item in matches:
        lines.append(f"{item['path']}:{item['line']}: {item['text']}")

    rendered = "\n".join(lines)
    runtime.renderer.display_info(rendered)
    return rendered, False


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
    "run_unit_test_coverage",
    "run_glob_search",
    "run_search_content",
    "parse_arguments",
]
