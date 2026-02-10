from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from bash_executor import CommandRejected, format_command_result, run_sandboxed_bash
from config_loader import load_config, DEFAULT_MODEL, save_config
from config_paths import get_config_path
from contextualizer import (
    read_file_slice,
    format_file_slice_for_prompt,
    DEFAULT_READ_LIMIT,
    MAX_READ_BYTES,
)

from cli_renderer import CLIRenderer
from ai_engine import AIEngine
from ai_engine import NEW_CONVERSATION_TOKEN
from inline_prompt_mode import parse_inline_prompt, run_inline_prompt


INSTALL_SH_URL = "https://raw.githubusercontent.com/ryangerardwilson/ai/main/install.sh"
PRIMARY_FLAG_SET = {"-h", "--help", "-v", "--version", "-V", "-u", "--upgrade"}


class Orchestrator:
    def __init__(self) -> None:
        self.config = load_config()
        self._config_path = get_config_path()
        show_reasoning = self.config.get("show_reasoning")
        if show_reasoning is None:
            show_reasoning = self.config.get("show_thinking", True)
        env_toggle = os.environ.get("AI_SHOW_REASONING")
        if env_toggle is None:
            env_toggle = os.environ.get("AI_SHOW_THINKING")
        if env_toggle is not None:
            show_reasoning = env_toggle.lower() not in {"0", "false", "no"}
        self.renderer = CLIRenderer(
            color_prefix=self._resolve_color(),
            show_reasoning=bool(show_reasoning),
        )
        self._bootstrap_config()
        self.engine = AIEngine(
            renderer=self.renderer,
            config=self.config,
            default_model=self.config.get("model", DEFAULT_MODEL),
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def run(self, argv: Iterable[str]) -> int:
        arg_list = list(argv)

        primary_rc = self._handle_primary_flags(arg_list)
        if primary_rc is not None:
            return primary_rc

        shell_invocation = self._detect_shell_invocation(arg_list)
        if shell_invocation is not None:
            command, scope = shell_invocation
            command = command.strip()
            if not command:
                self.renderer.display_error("Shell command cannot be empty.")
                return 1
            display = f"!{command}" if command else "!"
            self.renderer.display_user_prompt(display)
            return self._run_shell_command(command, scope)

        inline_parse = parse_inline_prompt(arg_list)
        if inline_parse is not None:
            if inline_parse.error:
                self.renderer.display_error(inline_parse.error)
                return 1
            if inline_parse.request is None:
                self.renderer.display_error("Inline prompt could not be parsed.")
                return 1
            return run_inline_prompt(
                prompt=inline_parse.request.prompt,
                scopes=inline_parse.request.scopes,
                renderer=self.renderer,
                config=self.config,
                default_model=self.engine.default_model,
            )

        if not arg_list:
            return self._start_interactive_session()

        args = self._parse_args(arg_list)
        context_defaults = self.config.get("context_settings", {})

        debug_stream = None
        close_debug_stream = False
        if getattr(args, "debug_reasoning", None):
            debug_value = args.debug_reasoning
            try:
                if debug_value is True:
                    debug_path = Path("debug.log").resolve()
                    debug_path.parent.mkdir(parents=True, exist_ok=True)
                    debug_stream = debug_path.open("w", encoding="utf-8")
                    close_debug_stream = True
                    self.renderer.display_info(f"Debug logging -> {debug_path}")
                else:
                    debug_path = Path(str(debug_value)).expanduser()
                    debug_path.parent.mkdir(parents=True, exist_ok=True)
                    debug_stream = debug_path.open("w", encoding="utf-8")
                    close_debug_stream = True
                    self.renderer.display_info(f"Debug logging -> {debug_path}")
                self.renderer.enable_debug_logging(debug_stream)
                self.engine.enable_api_debug(debug_stream)
            except OSError as exc:
                self.renderer.display_error(f"Failed to enable debug logging: {exc}")
                debug_stream = None
                close_debug_stream = False

        try:
            return self._execute_command(args, context_defaults)
        finally:
            if close_debug_stream and debug_stream and debug_stream is not sys.stderr:
                debug_stream.close()

    # ------------------------------------------------------------------
    # Shell helpers
    # ------------------------------------------------------------------
    def _detect_shell_invocation(self, args: list[str]) -> Optional[Tuple[str, Optional[str]]]:
        if not args:
            return None

        first = args[0]
        if first.startswith("!"):
            command = self._compose_shell_command(first[1:], args[1:])
            return command, None

        if len(args) >= 2 and args[1].startswith("!"):
            candidate_scope = Path(args[0]).expanduser()
            if candidate_scope.exists():
                command = self._compose_shell_command(args[1][1:], args[2:])
                return command, str(candidate_scope)

        return None

    @staticmethod
    def _compose_shell_command(head: str, tail: Iterable[str]) -> str:
        parts: list[str] = []
        head = (head or "").strip()
        if head:
            parts.append(head)
        for item in tail:
            if item:
                parts.append(item)
        return " ".join(parts)

    def _run_shell_command(self, command: str, scope: Optional[str]) -> int:
        repo_root = Path.cwd().resolve()
        cwd = repo_root

        if scope:
            scope_path = Path(scope).expanduser()
            if not scope_path.exists():
                self.renderer.display_error(f"Scope path not found: {scope_path}")
                return 1
            if scope_path.is_file():
                scope_path = scope_path.parent
            cwd = scope_path.resolve()

        try:
            result = run_sandboxed_bash(
                command,
                cwd=cwd,
                scope_root=repo_root,
                timeout=30,
                max_output_bytes=20000,
            )
        except CommandRejected as exc:
            self.renderer.display_error(f"command rejected: {exc}")
            return 1
        except Exception as exc:  # pragma: no cover - defensive guard
            self.renderer.display_error(f"error running command: {exc}")
            return 1

        formatted = format_command_result(result)
        if formatted:
            self.renderer.display_shell_output(formatted)
        return int(result.exit_code)

    # ------------------------------------------------------------------
    # Interactive helpers
    # ------------------------------------------------------------------
    def _start_interactive_session(self) -> int:
        self.renderer.display_info(
            "Interactive session started. Type your instruction at the prompt (Ctrl+D to exit)."
        )

        while True:
            instruction = self.renderer.prompt_follow_up()
            if instruction is None:
                return 0
            instruction = instruction.strip()
            if not instruction:
                self.renderer.display_info("Please provide an instruction or press Ctrl+D to exit.")
                continue
            if instruction == NEW_CONVERSATION_TOKEN:
                self.renderer.display_info("Starting fresh. Provide your instruction.")
                continue
            if instruction.startswith("!"):
                self.renderer.display_user_prompt(instruction)
                command_text = instruction[1:].strip()
                if not command_text:
                    self.renderer.display_error("Shell command cannot be empty.")
                    continue
                self._run_shell_command(command_text, None)
                continue
            self.renderer.display_user_prompt(instruction)
            return self.engine.run_conversation(
                instruction, None, display_prompt=False
            )

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------
    def _execute_command(
        self, args: argparse.Namespace, context_defaults: Dict[str, int]
    ) -> int:
        if args.read:
            return self._show_file_slice(
                args.read,
                offset=args.offset,
                limit=args.limit,
                max_bytes=args.max_bytes,
                defaults={
                    "limit": int(
                        context_defaults.get("read_limit", DEFAULT_READ_LIMIT)
                    ),
                    "max_bytes": int(context_defaults.get("max_bytes", MAX_READ_BYTES)),
                },
            )

        if getattr(args, "scope_or_prompt", None) or getattr(args, "prompt", None):
            return 1

        return self._start_interactive_session()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------
    def _bootstrap_config(self) -> None:
        config_missing = not self._config_path.exists()
        key_value = (self.config.get("openai_api_key") or "").strip()
        model_value = (self.config.get("model") or "").strip()
        dog_whistle = (self.config.get("dog_whistle") or "").strip()
        initial_key = key_value
        initial_model = model_value
        initial_dog = dog_whistle
        config_changed = False

        if config_missing:
            self.renderer.display_info(
                "Configuration file not found. Enter your OpenAI API key to set it up."
            )

        if not key_value:
            self.renderer.display_info(
                "OpenAI API key not found. Enter it to continue."
            )

        if config_missing or not key_value:
            prompt_label = (
                "OpenAI API key (press Enter to keep detected value): "
                if key_value
                else "OpenAI API key: "
            )
            while True:
                entered = self.renderer.prompt_text(prompt_label)
                if entered is None:
                    self.renderer.display_error("API key input cancelled. Exiting.")
                    sys.exit(1)
                entered = entered.strip()
                if entered:
                    key_value = entered
                    break
                if key_value:
                    break
                self.renderer.display_error("API key cannot be empty. Try again.")

        self.config["openai_api_key"] = key_value
        if key_value != initial_key:
            config_changed = True

        if config_missing or not initial_model:
            self.renderer.display_info(
                "Default model controls which OpenAI model is used for new sessions."
            )
        prompt: Optional[str] = None
        if config_missing or not initial_model:
            if model_value:
                prompt = f"Default model (Enter to keep '{model_value}', default {DEFAULT_MODEL}): "
            else:
                prompt = f"Default model (Enter to use {DEFAULT_MODEL}): "
        elif not model_value:
            prompt = f"Default model (Enter to use {DEFAULT_MODEL}): "

        if prompt is not None:
            entered = self.renderer.prompt_text(prompt)
            chosen = (entered or "").strip()
            if chosen:
                model_value = chosen
            elif not model_value:
                model_value = DEFAULT_MODEL

        if not model_value:
            model_value = DEFAULT_MODEL

        if model_value != initial_model:
            config_changed = True
        self.config["model"] = model_value

        if config_missing or not dog_whistle:
            self.renderer.display_info(
                "Choose your approval phrase (dog whistle). When you type it, I’m cleared to modify files or run shell commands. Until then I can still read files, glob directories, and search the repo—just not change it."
            )
            while True:
                prompt = (
                    f"Dog whistle phrase (Enter to keep '{dog_whistle}' or default 'jfdi'): "
                    if dog_whistle
                    else "Dog whistle phrase (default 'jfdi'): "
                )
                entered = self.renderer.prompt_text(prompt)
                if entered is None:
                    self.renderer.display_error("Dog whistle input cancelled. Exiting.")
                    sys.exit(1)
                entered = entered.strip()
                if entered:
                    dog_whistle = entered
                    break
                if dog_whistle:
                    break
                dog_whistle = "jfdi"
                break

        if not dog_whistle:
            dog_whistle = "jfdi"

        if dog_whistle != initial_dog:
            config_changed = True
        self.config["dog_whistle"] = dog_whistle

        if config_missing or config_changed:
            try:
                save_path = save_config(self.config)
            except OSError as exc:
                self.renderer.display_error(
                    f"Failed to update config at {self._config_path}: {exc}"
                )
            else:
                if config_missing:
                    self.renderer.display_info(f"Configuration saved to {save_path}.")
        elif not key_value or not model_value or not dog_whistle:
            self.renderer.display_error(
                "Configuration incomplete. Please rerun and provide the missing values."
            )
            sys.exit(1)

    # ------------------------------------------------------------------
    # Flag handling
    # ------------------------------------------------------------------
    def _handle_primary_flags(self, args: list[str]) -> Optional[int]:
        if not args:
            return None

        if not set(args).issubset(PRIMARY_FLAG_SET):
            return None

        try:
            show_help, show_version, do_upgrade = self._parse_primary_flags(args)
        except ValueError as exc:
            self.renderer.display_error(str(exc))
            return 1

        if show_help:
            self._print_help()
            return 0
        if show_version:
            try:
                from _version import __version__  # type: ignore
            except Exception:  # pragma: no cover - fallback
                __version__ = "0.0.0"
            self.renderer.display_info(__version__)
            return 0
        if do_upgrade:
            return self._run_upgrade()

        return 0

    @staticmethod
    def _parse_primary_flags(argv: Iterable[str]) -> tuple[bool, bool, bool]:
        show_help = show_version = do_upgrade = False
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

    def _run_upgrade(self) -> int:
        try:
            curl = subprocess.Popen(
                ["curl", "-fsSL", INSTALL_SH_URL],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            self.renderer.display_error("Upgrade requires curl")
            return 1

        try:
            bash = subprocess.Popen(["bash", "-s", "--", "-u"], stdin=curl.stdout)
            if curl.stdout is not None:
                curl.stdout.close()
        except FileNotFoundError:
            self.renderer.display_error("Upgrade requires bash")
            curl.terminate()
            curl.wait()
            return 1

        bash_rc = bash.wait()
        curl_rc = curl.wait()
        if curl_rc != 0:
            stderr = (
                curl.stderr.read().decode("utf-8", errors="replace")
                if curl.stderr
                else ""
            )
            if stderr:
                self.renderer.display_error(stderr)
            return curl_rc
        return bash_rc

    # ------------------------------------------------------------------
    # CLI support
    # ------------------------------------------------------------------
    def _parse_args(self, argv: list[str]) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description="Codex-style terminal assistant")
        parser.add_argument("--read", metavar="PATH", help="Preview a file slice")
        parser.add_argument(
            "--offset", type=int, default=None, help="0-based line offset"
        )
        parser.add_argument(
            "--limit", type=int, default=None, help="Number of lines to read"
        )
        parser.add_argument(
            "--max-bytes",
            dest="max_bytes",
            type=int,
            default=None,
            help="Maximum bytes to load",
        )
        parser.add_argument(
            "scope_or_prompt", nargs="?", help="(deprecated)"
        )
        parser.add_argument("prompt", nargs="*", help="(deprecated)")
        parser.add_argument(
            "-d",
            "--debug",
            dest="debug_reasoning",
            nargs="?",
            const=True,
            default=None,
            help="Enable reasoning debug logs (optionally write to file)",
        )
        return parser.parse_args(argv)

    def _show_file_slice(
        self,
        path_str: str,
        *,
        offset: Optional[int],
        limit: Optional[int],
        max_bytes: Optional[int],
        defaults: Dict[str, int],
    ) -> int:
        target = Path(path_str).expanduser()
        target = (
            (Path.cwd() / target).resolve()
            if not target.is_absolute()
            else target.resolve()
        )

        if not target.exists():
            self.renderer.display_error(f"File not found: {target}")
            return 1
        if target.is_dir():
            self.renderer.display_error(
                f"{target} is a directory. Use --read with files only."
            )
            return 1

        safe_offset = max(0, offset or 0)
        safe_limit = max(1, (limit or defaults.get("limit", DEFAULT_READ_LIMIT)))
        safe_bytes = max(1, (max_bytes or defaults.get("max_bytes", MAX_READ_BYTES)))

        file_slice = read_file_slice(
            target,
            offset=safe_offset,
            limit=safe_limit,
            max_bytes=safe_bytes,
        )
        rel_root = Path.cwd().resolve()
        self.renderer.display_info(
            format_file_slice_for_prompt(file_slice, rel_root=rel_root)
        )

        if file_slice.truncated:
            try:
                rel_target = target.relative_to(rel_root)
            except ValueError:
                rel_target = target
            next_offset = file_slice.last_line_read
            self.renderer.display_info(
                "\nTo continue reading: "
                f"ai --read {rel_target} --offset {next_offset} --limit {safe_limit}"
            )
        return 0

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    @staticmethod
    def _print_help() -> None:
        print(
            "ai - Codex-style terminal assistant\n\n"
            "Usage:\n"
            "  ai              Start an interactive session\n"
            "  ai 'question'   Run a one-shot inline prompt\n"
            "  ai PATH 'q'     Run an inline prompt scoped to PATH\n"
            "  ai '!command'   Run a sandboxed shell command immediately\n"
            "  ai --read PATH  Preview a file slice\n"
            "  ai -h           Show this help\n"
            "  ai -v           Show installed version\n"
            "  ai -u           Reinstall the latest release if a newer version exists"
        )

    @staticmethod
    def _resolve_color(candidate: Optional[str] = None) -> str:
        if candidate:
            return candidate
        env_color = os.environ.get("AI_COLOR")
        if env_color:
            return env_color
        return "\033[1;36m"
