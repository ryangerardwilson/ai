#!/usr/bin/env python3

from __future__ import annotations

import argparse
import difflib
import os
import re
import openai
import sys
import time
import subprocess
import tempfile
import signal
import threading
from pathlib import Path
from typing import Any, Dict, Sequence

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


def _is_responses_model(model: str) -> bool:
    return model in RESPONSES_ONLY_MODELS


def _print_help() -> None:
    print(
        "ai - Terminal AI assistant\n\n"
        "Usage:\n"
        "  ai               Launch the interactive chat session\n"
        "  ai <prompt...>   Send a one-off prompt\n"
        "  ai -e PATH ...   Rewrite a file via edit mode\n"
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
        description="Snarky AI chat interface with optional edit mode"
    )
    parser.add_argument(
        "-e",
        "--edit",
        metavar="PATH",
        help="Rewrite the given file according to the instruction",
    )
    parser.add_argument("prompt", nargs="*", help="Prompt or edit instruction")
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


def handle_edit_mode(
    path_str: str,
    instruction: str,
    model: str | None = None,
    config: Dict[str, Any] | None = None,
):
    target_path = Path(path_str).expanduser()
    if not target_path.exists():
        print(f"{target_path} doesn't exist. Check your spelling, hotshot.")
        return 1
    if target_path.is_dir():
        print(f"{target_path} is a directory, not a file. Try harder.")
        return 1

    try:
        original_text = target_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"{target_path} isn't UTF-8 text. I'm not hex-editing that for you.")
        return 1
    except OSError as exc:
        print(f"Couldn't read {target_path}: {exc}")
        return 1

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
        f"{original_text}"
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

    if proposed_text == original_text:
        print("Model produced identical content. Nothing to do.")
        return 0

    diff_lines = list(
        difflib.unified_diff(
            original_text.splitlines(),
            proposed_text.splitlines(),
            fromfile=str(target_path),
            tofile=f"{target_path} (proposed)",
            lineterm="",
        )
    )

    if not diff_lines:
        print("No visible diff. Maybe your instruction was nonsense.")
        return 0

    diff_output = add_line_numbers_to_diff(diff_lines)
    print(diff_output)

    confirmation = input("Apply changes? [y/N]: ").strip().lower()
    if confirmation not in {"y", "yes"}:
        print("Changes discarded. Maybe next time.")
        return 0

    final_text = proposed_text
    if original_text.endswith("\n") and not final_text.endswith("\n"):
        final_text += "\n"

    try:
        existing_mode = target_path.stat().st_mode
        target_path.write_text(final_text, encoding="utf-8")
        os.chmod(target_path, existing_mode)
    except Exception as exc:
        print(f"Failed to write {target_path}: {exc}")
        return 1

    print(f"Applied changes to {target_path}.")
    return 0


def main(argv=None):
    arg_list = list(sys.argv[1:] if argv is None else argv)

    primary_rc = _handle_primary_flags(arg_list)
    if primary_rc is not None:
        return primary_rc

    config = load_config()

    args = parse_args(arg_list)

    if args.edit:
        instruction = " ".join(args.prompt).strip()
        if not instruction:
            print("Give me an instruction after the file path, pal.")
            return 1
        return handle_edit_mode(args.edit, instruction, config=config)

    prompt = " ".join(args.prompt).strip()
    if prompt:
        chat = AIChat(config=config, mode="prompt")
        appended_prompt = (
            f"{prompt}\n\nRespond as concisely as possible in less than 200 words."
        )
        chat.messages.append({"role": "user", "content": appended_prompt})
        try:
            chat.stream_response(show_loader=True, use_color=False)
        except Exception as e:
            print(f"Error: {str(e)}. Sort your dependencies or network, dammit.")
            chat.cleanup_history_file()
            return 1
        else:
            chat.cleanup_history_file()
            return 0

    chat = AIChat(config=config)
    chat.run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
