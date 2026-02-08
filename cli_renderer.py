from __future__ import annotations

import difflib
import os
import re
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
import termios
import threading
import time
import tty
from collections import deque
from pathlib import Path
from typing import Iterable, Optional, List, TextIO, Deque, Any, cast

try:  # Optional readline support for interactive prompts
    import readline as _readline
except ImportError:  # pragma: no cover - readline absent on some platforms
    _readline = None


class CLIRenderer:
    """Console renderer for the ai CLI."""

    ANSI_WHITE = "\033[97m"
    ANSI_MEDIUM_GRAY = "\033[38;5;245m"
    ANSI_DIM_GRAY = "\033[90m"
    ANSI_DARKER_GRAY = "\033[38;5;240m"
    ANSI_REASONING = "\033[38;5;242m"
    ANSI_RESET = "\033[0m"
    NEW_CONVERSATION_TOKEN = "<<NEW_CONVERSATION>>"

    def __init__(
        self, *, color_prefix: str = "\033[1;36m", show_reasoning: bool = True
    ) -> None:
        self.color_prefix = color_prefix
        self._supports_color = sys.stdout.isatty()
        self._loader_thread: Optional[threading.Thread] = None
        self._loader_stop: Optional[threading.Event] = None
        self._readline = _readline
        self._readline_prompt: str = ""
        self._completion_messages: List[str] = []
        self._show_reasoning = show_reasoning
        self._reasoning_buffers: dict[str, str] = {}
        self._active_reasoning: Optional[str] = None
        self._reasoning_line_len = 0
        self._assistant_streams: dict[str, str] = {}
        self._assistant_order: list[str] = []
        self._reasoning_placeholder_printed = False
        self._printed_reasoning_snippets: set[str] = set()
        self._printed_reasoning_ids: set[str] = set()
        self._reasoning_last_snippet: dict[str, str] = {}
        debug_env = os.environ.get("AI_DEBUG_REASONING") or os.environ.get(
            "AI_DEBUG_API"
        )
        self._debug_reasoning = bool(debug_env)
        self._debug_stream: TextIO = sys.stderr
        self._suppress_next_user_prompt = False
        self._hotkey_thread: Optional[threading.Thread] = None
        self._hotkey_stop: Optional[threading.Event] = None
        self._hotkey_events: Deque[str] = deque()
        self._hotkey_lock = threading.Lock()
        self._hotkey_fd: Optional[int] = None
        self._hotkey_termios: Optional[Any] = None

    def _log_reasoning(self, message: str) -> None:
        if self._debug_reasoning:
            print(f"[reasoning-debug] {message}", file=self._debug_stream)

    def enable_debug_logging(self, stream: TextIO) -> None:
        self._debug_reasoning = True
        self._debug_stream = stream

    def _enqueue_hotkey_event(self, name: str) -> None:
        if name not in {"quit", "retry"}:
            return
        with self._hotkey_lock:
            self._hotkey_events.append(name)

    def start_hotkey_listener(self) -> None:
        if self._hotkey_thread and self._hotkey_thread.is_alive():
            return
        if not sys.stdin.isatty():
            return
        try:
            fd = sys.stdin.fileno()
        except (OSError, ValueError):
            return

        try:
            original_attrs = termios.tcgetattr(fd)
        except termios.error:
            original_attrs = None

        stop_event = threading.Event()
        with self._hotkey_lock:
            self._hotkey_events.clear()
        self._hotkey_stop = stop_event
        self._hotkey_fd = fd
        self._hotkey_termios = original_attrs

        def worker() -> None:
            try:
                if original_attrs is not None:
                    tty.setcbreak(fd)
                    try:
                        attrs = termios.tcgetattr(fd)
                        ix_flags = termios.IXON
                        ix_off = getattr(termios, "IXOFF", 0)
                        if isinstance(ix_off, int):
                            ix_flags |= ix_off
                        attrs[0] &= ~ix_flags
                        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
                    except termios.error:
                        pass
            except Exception:
                pass

            try:
                while not stop_event.is_set():
                    try:
                        ready, _, _ = select.select([fd], [], [], 0.1)
                    except (OSError, ValueError):
                        break
                    if not ready:
                        continue
                    try:
                        data = os.read(fd, 1)
                    except OSError:
                        break
                    if not data:
                        continue
                    key_code = data[0]
                    if key_code in {ord("q"), ord("Q")}:
                        self._enqueue_hotkey_event("quit")
                    elif key_code in {ord("r"), ord("R")}:
                        self._enqueue_hotkey_event("retry")
            finally:
                if original_attrs is not None:
                    try:
                        termios.tcsetattr(
                            fd, termios.TCSADRAIN, cast(Any, original_attrs)
                        )
                    except termios.error:
                        pass

        thread = threading.Thread(target=worker, daemon=True)
        self._hotkey_thread = thread
        thread.start()

    def stop_hotkey_listener(self) -> None:
        stop_event = self._hotkey_stop
        if stop_event:
            stop_event.set()
        thread = self._hotkey_thread
        if thread and thread.is_alive():
            thread.join(timeout=0.2)
        if self._hotkey_termios is not None and self._hotkey_fd is not None:
            try:
                termios.tcsetattr(
                    self._hotkey_fd, termios.TCSADRAIN, cast(Any, self._hotkey_termios)
                )
            except termios.error:
                pass
        self._hotkey_thread = None
        self._hotkey_stop = None
        self._hotkey_fd = None
        self._hotkey_termios = None

    def poll_hotkey_event(self) -> Optional[str]:
        with self._hotkey_lock:
            if self._hotkey_events:
                return self._hotkey_events.popleft()
        return None

    def _is_summary_id(self, reasoning_id: str) -> bool:
        return ":summary:" in reasoning_id

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------
    def display_info(self, text: str) -> None:
        if text:
            print(self._colorize(text, self.ANSI_MEDIUM_GRAY))

    def display_error(self, text: str) -> None:
        if text:
            if sys.stderr.isatty():
                print(self._colorize(text, self.ANSI_MEDIUM_GRAY), file=sys.stderr)
            else:
                print(text, file=sys.stderr)

    def display_reasoning(self, text: str) -> None:
        if text:
            print(self._colorize(f"# Reasoning\n{text}\n", self.ANSI_DIM_GRAY))

    def display_assistant_message(self, text: str) -> None:
        if text:
            prefix = "🤖 > "
            print(self._colorize(prefix + text, self.ANSI_MEDIUM_GRAY))

    def display_shell_output(self, text: str) -> None:
        if text:
            print(self._colorize(text, self.ANSI_MEDIUM_GRAY))

    def display_plan_update(self, plan: str, explanation: Optional[str]) -> None:
        if plan:
            print(self._colorize("# Updated Plan\n" + plan, self.ANSI_MEDIUM_GRAY))
        if explanation:
            print(
                self._colorize(
                    "# Plan Explanation\n" + explanation, self.ANSI_MEDIUM_GRAY
                )
            )

    # ------------------------------------------------------------------
    # Prompts
    # ------------------------------------------------------------------
    def prompt_confirm(self, prompt: str, *, default_no: bool = True) -> bool:
        try:
            response = input(prompt).strip().lower()
        except KeyboardInterrupt:
            print("\nInterrupted while awaiting confirmation.")
            raise
        except EOFError:
            return False

        response = re.sub(r"[^a-z]", "", response)
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
            "do",
            "doit",
            "write",
            "writeit",
            "save",
        }
        if default_no:
            return response in positive
        return response not in {"", "n", "no"}

    def prompt_text(self, prompt: str) -> Optional[str]:
        try:
            value = input(prompt)
        except KeyboardInterrupt:
            print("\nInterrupted.")
            raise
        except EOFError:
            return None
        return value

    def prompt_follow_up(self) -> Optional[str]:
        while True:
            if self._readline:
                self._readline_prompt = "💬 > "
            self._completion_messages.clear()
            try:
                raw_value = input("💬 > ")
            except KeyboardInterrupt:
                print("\nInterrupted by user.")
                return None
            except EOFError:
                print()
                return None

            trimmed = raw_value.strip()
            stripped_leading = raw_value.lstrip()

            if stripped_leading.lower().startswith("v"):
                command, sep, remainder = stripped_leading.partition(" ")
                if command.lower() == "v":
                    seed_text = remainder if sep else ""
                    edited = self.edit_prompt(seed_text)
                    if edited is None:
                        continue
                    edited = edited.strip()
                    if not edited:
                        self.display_info("Prompt cancelled (empty message).")
                        continue
                    return edited

            if trimmed:
                command_lower = trimmed.lower()
                if command_lower == "help":
                    self.display_info(
                        "# Help\n"
                        "- Enter a question or instruction to continue the conversation.\n"
                        "- Prefix a shell command with `!` (e.g., `!ls`).\n"
                        "- While a reply streams, press `q` to cancel or `r` to retry the prompt.\n"
                        "- Use `/v` or `v` to draft the next prompt in Vim."
                    )
                    continue
                if command_lower == "new":
                    self.display_info("Context reset.")
                    return self.NEW_CONVERSATION_TOKEN
                self._suppress_next_user_prompt = True
                return trimmed

            # Empty input mirrors previous behaviour: exit conversation
            return ""

    def consume_completion_messages(self) -> list[str]:
        messages = self._completion_messages[:]
        self._completion_messages.clear()
        return messages

    # ------------------------------------------------------------------
    # File review helpers
    # ------------------------------------------------------------------
    def review_file_update(
        self,
        target_path: Path,
        display_path: Path,
        old_text: str,
        new_text: str,
        *,
        auto_apply: bool = False,
    ) -> str:
        diff_lines = list(
            difflib.unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                fromfile=str(display_path),
                tofile=f"{display_path} (proposed)",
                lineterm="",
            )
        )

        if not diff_lines:
            return "no_change"

        print(self._format_diff(diff_lines))

        if new_text == "":
            print(self._format_status("auto", display_path, prefix="removing "))
            return "delete_requested"

        print(self._format_status("auto", display_path, prefix="applying changes to "))

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(
                new_text + ("\n" if not new_text.endswith("\n") else ""),
                encoding="utf-8",
            )
            os.chmod(target_path, 0o644)
            print(self._format_status("applied", display_path))
            return "applied"
        except Exception as exc:  # pragma: no cover - filesystem errors
            print(
                self._format_status(
                    "error", display_path, suffix=f": failed to write ({exc})"
                )
            )
            return f"error: failed to write {display_path}: {exc}"

    # ------------------------------------------------------------------
    # Loader utilities
    # ------------------------------------------------------------------
    def start_loader(
        self,
    ) -> tuple[Optional[threading.Event], Optional[threading.Thread]]:
        if self._show_reasoning and self._active_reasoning:
            return None, None
        if self._assistant_streams:
            return None, None
        if self._loader_thread and self._loader_thread.is_alive():
            return self._loader_stop, self._loader_thread

        if not sys.stdout.isatty():
            self._loader_stop = None
            self._loader_thread = None
            return None, None

        stop_event = threading.Event()
        frames = [
            "◐" * 12,
            "◓" * 12,
            "◑" * 12,
            "◒" * 12,
            "◐◓◑◒◐◓◑◒◐◓◑◒",
            "◓◑◒◐◓◑◒◐◓◑◒◐",
            "◑◒◐◓◑◒◐◓◑◒◐◓",
            "◒◐◓◑◒◐◓◑◒◐◓◑",
        ]

        def loader() -> None:
            idx = 0
            if self._supports_color:
                print("\033[?25l", end="", flush=True)
            while not stop_event.is_set():
                frame = frames[idx % len(frames)]
                idx += 1
                if self._supports_color:
                    frame = f"{self.ANSI_WHITE}{frame}{self.ANSI_RESET}"
                print(f"\r{frame:<24}", end="", flush=True)
            time.sleep(0.06)
            print("\r" + " " * 24 + "\r", end="", flush=True)
            if self._supports_color:
                print("\033[?25h", end="", flush=True)

        thread = threading.Thread(target=loader, daemon=True)
        thread.start()
        self._loader_stop = stop_event
        self._loader_thread = thread
        return stop_event, thread

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _format_diff(self, diff_lines: Iterable[str]) -> str:
        formatted: list[str] = []
        line_with_numbers = ""
        old_no = new_no = None
        header_pattern = re.compile(
            r"^@@ -(?P<old>\d+)(?:,(?P<old_count>\d+))? \+(?P<new>\d+)(?:,(?P<new_count>\d+))? @@"
        )

        colorize = sys.stdout.isatty()

        for line in diff_lines:
            if line.startswith("@@"):
                match = header_pattern.match(line)
                if match:
                    old_no = int(match.group("old"))
                    new_no = int(match.group("new"))
                formatted.append(line)
                continue

            if (
                line.startswith("--- ")
                or line.startswith("+++ ")
                or line.startswith("diff ")
            ):
                formatted.append(line)
                continue

            if not line or line[0] not in {" ", "-", "+"}:
                formatted.append(line)
                continue

            prefix = line[:1]
            old_label = new_label = ""
            line_with_numbers = line

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
            else:
                if old_no is None:
                    old_no = 1
                if new_no is None:
                    new_no = 1
                old_label = str(old_no)
                new_label = str(new_no)
                old_no += 1
                new_no += 1

            line_with_numbers = f"{old_label:>6} {new_label:>6} {line}"

            if colorize and prefix:
                if prefix == "+":
                    line_with_numbers = (
                        f"{self.ANSI_WHITE}{line_with_numbers}{self.ANSI_RESET}"
                    )
                elif prefix == "-":
                    line_with_numbers = (
                        f"{self.ANSI_DIM_GRAY}{line_with_numbers}{self.ANSI_RESET}"
                    )
                else:
                    line_with_numbers = (
                        f"{self.ANSI_DIM_GRAY}{line_with_numbers}{self.ANSI_RESET}"
                    )

            formatted.append(line_with_numbers)

        return "\n".join(formatted)

    def _format_status(
        self, label: str, path: Path, *, prefix: str = "", suffix: str = ""
    ) -> str:
        tag = f"[{label}]"
        if self._supports_color:
            if label.lower() == "applied":
                tag = f"{self.ANSI_WHITE}{tag}{self.ANSI_RESET}"
            else:
                tag = f"{self.ANSI_DIM_GRAY}{tag}{self.ANSI_RESET}"
        body = f"{prefix}{path}"
        return f"{tag} {body}{suffix}" if suffix else f"{tag} {body}"

    def _colorize(self, text: str, color: str) -> str:
        if not text or not self._supports_color:
            return text
        return f"{color}{text}{self.ANSI_RESET}"

    def stop_loader(self) -> None:
        if self._loader_stop:
            self._loader_stop.set()
        if self._loader_thread and self._loader_thread.is_alive():
            self._loader_thread.join()
        self._loader_stop = None
        self._loader_thread = None
        if self._supports_color:
            print("\033[?25h", end="", flush=True)

    # ------------------------------------------------------------------
    # Prompt editing helper
    # ------------------------------------------------------------------
    def edit_prompt(self, seed_text: str = "") -> Optional[str]:
        return self._edit_prompt_via_editor(seed_text)

    def display_user_prompt(self, prompt: str) -> None:
        if not prompt:
            return
        if self._suppress_next_user_prompt:
            self._suppress_next_user_prompt = False
            return
        sanitized = prompt.replace("\r\n", "\n").replace("\r", "\n")
        sanitized = sanitized.replace("\n", " ⏎ ")
        limit = 500
        truncated = sanitized if len(sanitized) <= limit else sanitized[:limit] + "…"
        formatted = f"💬 > {truncated}" if truncated else "💬 >"
        if self._supports_color:
            print(f"{self.ANSI_DARKER_GRAY}{formatted}{self.ANSI_RESET}")
        else:
            print(formatted)

    def start_reasoning(self, reasoning_id: str) -> None:
        if not self._show_reasoning:
            return
        is_summary = self._is_summary_id(reasoning_id)
        self._log_reasoning(f"start id={reasoning_id}")
        self._reasoning_buffers[reasoning_id] = ""
        self._active_reasoning = reasoning_id
        self._reasoning_line_len = 0
        self._printed_reasoning_ids.discard(reasoning_id)
        self._reasoning_last_snippet.pop(reasoning_id, None)
        if self._supports_color and sys.stdout.isatty() and not is_summary:
            self._render_reasoning_line(reasoning_id)
        else:
            if not self._reasoning_placeholder_printed and not is_summary:
                print("🤖 thinking…")
                self._reasoning_placeholder_printed = True

    def update_reasoning(self, reasoning_id: str, delta: str) -> None:
        if not self._show_reasoning:
            return
        existing = self._reasoning_buffers.get(reasoning_id, "")
        existing += delta
        self._reasoning_buffers[reasoning_id] = existing
        self._active_reasoning = reasoning_id
        self._log_reasoning(
            f"update id={reasoning_id} delta_len={len(delta)} buffer_len={len(existing)}"
        )
        if self._is_summary_id(reasoning_id):
            return
        if self._supports_color and sys.stdout.isatty():
            self._render_reasoning_line(reasoning_id)

    def finish_reasoning(self, reasoning_id: str, final: Optional[str] = None) -> None:
        if not self._show_reasoning:
            return
        buffer = (
            final
            if final is not None
            else self._reasoning_buffers.get(reasoning_id, "")
        )
        if reasoning_id in self._reasoning_buffers:
            del self._reasoning_buffers[reasoning_id]
        if not buffer:
            buffer = ""
        already_printed = reasoning_id in self._printed_reasoning_ids
        snippet_full = (
            buffer.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ⏎ ")
        )
        self._log_reasoning(
            f"finish id={reasoning_id} already_printed={already_printed} snippet_len={len(snippet_full)}"
        )
        if self._supports_color and sys.stdout.isatty():
            if not already_printed:
                last = self._reasoning_last_snippet.get(reasoning_id)
                if last != snippet_full:
                    line = f"🤖 {snippet_full}" if snippet_full else "🤖"
                    padding = max(0, self._reasoning_line_len - len(line))
                    print(
                        f"\r{self.ANSI_REASONING}{line}{self.ANSI_RESET}{' ' * padding}"
                    )
                    self._reasoning_last_snippet[reasoning_id] = snippet_full
                print()
        elif buffer and not sys.stdout.isatty():
            normalized = " ".join(snippet_full.split())
            if normalized and normalized not in self._printed_reasoning_snippets:
                self._log_reasoning(
                    f"finish non-tty print id={reasoning_id} normalized_len={len(normalized)}"
                )
                print(f"🤖 {snippet_full}")
                self._printed_reasoning_snippets.add(normalized)
        self._printed_reasoning_ids.add(reasoning_id)
        self._reasoning_placeholder_printed = False
        if self._active_reasoning == reasoning_id:
            self._active_reasoning = None
            self._reasoning_line_len = 0
        self._reasoning_last_snippet.pop(reasoning_id, None)

    def _render_reasoning_line(self, reasoning_id: str) -> None:
        if not self._show_reasoning:
            return
        buffer = self._reasoning_buffers.get(reasoning_id, "")
        snippet = buffer.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ⏎ ")
        snippet = snippet[-200:] if snippet else "thinking…"
        if self._reasoning_last_snippet.get(reasoning_id) == snippet:
            self._log_reasoning(
                f"render dedupe id={reasoning_id} snippet_len={len(snippet)}"
            )
            return
        self._reasoning_last_snippet[reasoning_id] = snippet
        self._log_reasoning(
            f"render id={reasoning_id} snippet_len={len(snippet)} supports_color={self._supports_color}"
        )
        line = f"🤖 {snippet}"
        if self._supports_color and sys.stdout.isatty():
            padding = max(0, self._reasoning_line_len - len(line))
            print(
                f"\r{self.ANSI_REASONING}{line}{self.ANSI_RESET}{' ' * padding}",
                end="",
                flush=True,
            )
            self._reasoning_line_len = len(line)
        else:
            print(line)

    def start_assistant_stream(self, stream_id: str) -> None:
        if stream_id in self._assistant_streams:
            return
        if self._active_reasoning:
            print()
            self._active_reasoning = None
            self._reasoning_line_len = 0
        self._assistant_streams[stream_id] = ""
        self._assistant_order.append(stream_id)
        if self._supports_color and sys.stdout.isatty():
            prefix = f"{self.ANSI_MEDIUM_GRAY}🤖 > {self.ANSI_RESET}"
            print(prefix, end="", flush=True)

    def update_assistant_stream(self, stream_id: str, delta: str) -> None:
        buffer = self._assistant_streams.get(stream_id)
        if buffer is None:
            self.start_assistant_stream(stream_id)
            buffer = self._assistant_streams.get(stream_id, "")
        if delta:
            new_value = buffer + delta
            self._assistant_streams[stream_id] = new_value
            if self._supports_color and sys.stdout.isatty():
                print(
                    f"{self.ANSI_MEDIUM_GRAY}{delta}{self.ANSI_RESET}",
                    end="",
                    flush=True,
                )

    def finish_assistant_stream(
        self, stream_id: str, final_text: Optional[str] = None
    ) -> None:
        buffer = self._assistant_streams.pop(stream_id, "")
        if stream_id in self._assistant_order:
            self._assistant_order.remove(stream_id)
        if final_text is not None and final_text != buffer:
            missing = final_text[len(buffer) :]
            if missing and self._supports_color and sys.stdout.isatty():
                print(
                    f"{self.ANSI_MEDIUM_GRAY}{missing}{self.ANSI_RESET}",
                    end="",
                    flush=True,
                )
        if self._supports_color and sys.stdout.isatty():
            print()

    def _edit_prompt_via_editor(self, seed_text: str) -> Optional[str]:
        candidates = [
            os.environ.get("AI_PROMPT_EDITOR"),
            os.environ.get("EDITOR"),
            os.environ.get("VISUAL"),
            "vim",
        ]

        editor_args: Optional[List[str]] = None
        for candidate in candidates:
            if not candidate:
                continue
            try:
                parts = shlex.split(candidate)
            except ValueError:
                continue
            if not parts:
                continue
            if shutil.which(parts[0]) is None:
                continue
            editor_args = parts
            break

        if editor_args is None:
            self.display_error(
                "No editor available for /v. Set AI_PROMPT_EDITOR or install vim."
            )
            return None

        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                "w+", delete=False, encoding="utf-8"
            ) as handle:
                temp_path = handle.name
                if seed_text:
                    handle.write(seed_text)
                    if not seed_text.endswith("\n"):
                        handle.write("\n")
                handle.flush()

            rc = subprocess.call(editor_args + [temp_path])
            if rc != 0:
                self.display_error(f"Editor exited with status {rc}; prompt unchanged.")
                return None

            with open(temp_path, "r", encoding="utf-8") as reader:
                return reader.read()
        except FileNotFoundError:
            self.display_error(
                f"Editor '{editor_args[0] if editor_args else 'vim'}' not found."
            )
            return None
        except Exception as exc:
            self.display_error(f"Failed to launch editor: {exc}")
            return None
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
