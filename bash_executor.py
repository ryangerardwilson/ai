#!/usr/bin/env python3
"""Sandboxed bash execution helpers for ai bash mode."""

from __future__ import annotations

import os
import shlex
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DISALLOWED_SUBSTRINGS: tuple[str, ...] = (
    "sudo",
    "chmod",
    "chown",
    "chgrp",
    "mkfs",
    "|&",
    ";&",
    "shutdown",
    "reboot",
    "systemctl",
    "kill",
    ":>",
)


class CommandRejected(Exception):
    """Raised when a command violates sandboxing rules."""


@dataclass
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool


def _looks_like_path(token: str) -> bool:
    return token.startswith("/") or token.startswith("..")


def _references_git(token: str) -> bool:
    return ".git" in token


def _tokenize(command: str) -> Iterable[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _validate_command(command: str) -> None:
    lowered = command.lower()
    if any(marker in lowered for marker in DISALLOWED_SUBSTRINGS):
        raise CommandRejected("Command rejected: contains disallowed operation")

    tokens = list(_tokenize(command))
    if any(_looks_like_path(token) for token in tokens):
        raise CommandRejected(
            "Command rejected: absolute or parent paths are not allowed"
        )
    if any(_references_git(token) for token in tokens):
        raise CommandRejected("Command rejected: .git modifications are not permitted")


def run_sandboxed_bash(
    command: str,
    cwd: Path,
    scope_root: Path,
    *,
    timeout: int,
    max_output_bytes: int,
) -> CommandResult:
    command = command.strip()
    if not command:
        raise CommandRejected("Empty command")

    cwd = cwd.resolve()
    scope_root = scope_root.resolve()
    if not cwd.is_dir():
        raise CommandRejected(f"Working directory {cwd} does not exist")
    if scope_root not in cwd.parents and scope_root != cwd:
        raise CommandRejected("Command scope violation")

    _validate_command(command)

    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["LANG"] = "C"

    try:
        completed = subprocess.run(
            ["bash", "-lc", command],
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_raw = exc.stdout
        stderr_raw = exc.stderr

        if isinstance(stdout_raw, bytes):
            stdout = stdout_raw.decode("utf-8", errors="replace")
        else:
            stdout = stdout_raw or ""

        if isinstance(stderr_raw, bytes):
            stderr = stderr_raw.decode("utf-8", errors="replace")
        else:
            stderr = stderr_raw or ""

        return CommandResult(
            command=command,
            exit_code=124,
            stdout=stdout,
            stderr=stderr + "\nCommand timed out",
            truncated=False,
        )

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    truncated = False

    def _truncate(text: str) -> str:
        nonlocal truncated
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) <= max_output_bytes:
            return text
        truncated = True
        return encoded[:max_output_bytes].decode("utf-8", errors="replace")

    stdout = _truncate(stdout)
    stderr = _truncate(stderr)

    return CommandResult(
        command=command,
        exit_code=completed.returncode,
        stdout=stdout,
        stderr=stderr,
        truncated=truncated,
    )


def format_command_result(result: CommandResult) -> str:
    sections = []
    if result.stdout:
        sections.append("stdout:\n" + result.stdout.rstrip())
    if result.stderr:
        sections.append("stderr:\n" + result.stderr.rstrip())
    if result.truncated:
        sections.append("[output truncated]")
    return textwrap.dedent("\n\n".join(sections)).strip()


__all__ = [
    "CommandResult",
    "CommandRejected",
    "run_sandboxed_bash",
    "format_command_result",
]
