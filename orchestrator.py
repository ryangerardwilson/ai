from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional

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

        if len(arg_list) == 1 and arg_list[0].lower() == "v":
            edited = self.renderer.edit_prompt()
            if edited is None:
                return 1
            prompt_text = edited.strip()
            if not prompt_text:
                self.renderer.display_info("Prompt cancelled (empty message).")
                return 0
            self.renderer.display_user_prompt(prompt_text)
            return self.engine.run_conversation(prompt_text, None, display_prompt=False)

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

        scope_candidate = args.scope_or_prompt
        prompt_components = list(args.prompt)
        scope_arg: Optional[str] = None

        if scope_candidate:
            candidate_path = Path(scope_candidate).expanduser()
            if candidate_path.exists():
                scope_arg = str(candidate_path)
                prompt_text = " ".join(prompt_components).strip()
                if candidate_path.is_file():
                    if not prompt_text:
                        self.renderer.display_info(
                            "Provide an instruction after the file path."
                        )
                        return 1
                    return self.engine.run_edit(scope_arg, prompt_text)
                else:
                    if not prompt_text:
                        self.renderer.display_info("Provide a question or instruction.")
                        return 1
                    return self.engine.run_conversation(
                        prompt_text, scope_arg, display_prompt=False
                    )
            else:
                prompt_components.insert(0, scope_candidate)

        prompt_text = " ".join(prompt_components).strip()
        if not prompt_text:
            self._print_help()
            return 1

        return self.engine.run_conversation(
            prompt_text, scope_arg, display_prompt=False
        )

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------
    def _bootstrap_config(self) -> None:
        config_missing = not self._config_path.exists()
        key_value = (self.config.get("openai_api_key") or "").strip()
        model_value = (self.config.get("model") or "").strip()
        initial_key = key_value
        initial_model = model_value
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
                prompt = (
                    f"Default model (Enter to keep '{model_value}', default {DEFAULT_MODEL}): "
                )
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

        if config_missing or config_changed:
            try:
                save_path = save_config(self.config)
            except OSError as exc:
                self.renderer.display_error(
                    f"Failed to update config at {self._config_path}: {exc}"
                )
            else:
                if config_missing:
                    self.renderer.display_info(
                        f"Configuration saved to {save_path}."
                    )

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
            "scope_or_prompt", nargs="?", help="Optional scope or beginning of prompt"
        )
        parser.add_argument("prompt", nargs="*", help="Additional prompt words")
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
            '  ai [SCOPE] "question or instruction"\n'
            "      SCOPE (optional) is a file or directory to focus on\n"
            "      When SCOPE is a file, ai proposes edits with diff approval\n"
            "  ai -h            Show this help\n"
            "  ai -v            Show installed version\n"
            "  ai -u            Reinstall the latest release if a newer version exists"
        )

    @staticmethod
    def _resolve_color(candidate: Optional[str] = None) -> str:
        if candidate:
            return candidate
        env_color = os.environ.get("AI_COLOR")
        if env_color:
            return env_color
        return "\033[1;36m"
