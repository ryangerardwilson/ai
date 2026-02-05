from __future__ import annotations

import difflib
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Iterable, Optional, List

try:  # Optional readline support for interactive prompts
    import readline as _readline
except ImportError:  # pragma: no cover - readline absent on some platforms
    _readline = None


class CLIRenderer:
    """Console renderer for the ai CLI."""

    ANSI_WHITE = "\033[97m"
    ANSI_MEDIUM_GRAY = "\033[38;5;245m"
    ANSI_DIM_GRAY = "\033[90m"
    ANSI_RESET = "\033[0m"

    def __init__(self, *, color_prefix: str = "\033[1;36m") -> None:
        self.color_prefix = color_prefix
        self._supports_color = sys.stdout.isatty()
        self._loader_thread: Optional[threading.Thread] = None
        self._loader_stop: Optional[threading.Event] = None
        self._readline = _readline
        self._readline_prompt: str = ""
        self._completion_messages: List[str] = []

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
        if self._readline:
            self._readline_prompt = "QR > "
        self._completion_messages.clear()
        try:
            return input("QR > ").strip()
        except KeyboardInterrupt:
            print("\nInterrupted by user.")
            return None
        except EOFError:
            print()
            return None

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
            print(
                self._format_status(
                    "skip", display_path, suffix=": no changes detected"
                )
            )
            return "no_change"

        print(self._format_diff(diff_lines))

        if auto_apply:
            print(
                self._format_status("auto", display_path, prefix="applying changes to ")
            )
            confirmed = True
        else:
            confirmed = self.prompt_confirm(
                f"Apply changes to {display_path}? [y/N]: ", default_no=True
            )

        if not confirmed:
            print(self._format_status("skip", display_path))
            return "user_rejected"

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
