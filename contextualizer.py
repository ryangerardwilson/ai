#!/usr/bin/env python3
"""Collect repository context for the Codex-style analysis loop."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

DEFAULT_FILE_BYTES = 8000
MAX_FILES = 8
INTERESTING_PREFIXES = ("readme", "docs", "architecture", "overview")
INTERESTING_SUFFIXES = (
    "README.md",
    "README.txt",
    "README",
    "main.py",
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "setup.py",
)


@dataclass
class CollectedContext:
    scope_root: Path
    listing: List[str]
    files: List[tuple[Path, str, bool]]  # (path, text, truncated)


def _safe_read(path: Path, byte_limit: int = DEFAULT_FILE_BYTES) -> tuple[str, bool]:
    try:
        data = path.read_bytes()
    except Exception as exc:  # pragma: no cover - filesystem errors
        return f"<failed to read: {exc}>", False

    truncated = False
    if len(data) > byte_limit:
        data = data[:byte_limit]
        truncated = True

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
        truncated = True
    return text, truncated


def _discover_candidates(scope_root: Path) -> List[Path]:
    entries: List[Path] = []
    for entry in sorted(scope_root.iterdir()):
        if entry.name.startswith(".") and entry.name not in {".env", ".gitignore"}:
            continue
        if entry.is_dir():
            entries.append(entry)
        else:
            entries.append(entry)
    candidates: List[Path] = []
    for preferred in INTERESTING_SUFFIXES:
        path = scope_root / preferred
        if path.exists():
            candidates.append(path)
    for entry in entries:
        if entry in candidates:
            continue
        lower = entry.name.lower()
        if any(lower.startswith(prefix) for prefix in INTERESTING_PREFIXES):
            candidates.append(entry)
    for entry in entries:
        if entry not in candidates:
            candidates.append(entry)
    return candidates


def collect_context(scope: Path, limit_bytes: int = DEFAULT_FILE_BYTES) -> CollectedContext:
    scope_root = scope.resolve()
    listing: List[str] = []
    try:
        for entry in sorted(scope_root.iterdir()):
            mark = "/" if entry.is_dir() else ""
            listing.append(entry.name + mark)
    except FileNotFoundError:
        listing.append("<scope directory missing>")

    files: List[tuple[Path, str, bool]] = []
    for candidate in _discover_candidates(scope_root):
        if len(files) >= MAX_FILES:
            break
        if candidate.is_dir():
            continue
        text, truncated = _safe_read(candidate, byte_limit=limit_bytes)
        files.append((candidate, text, truncated))

    return CollectedContext(scope_root=scope_root, listing=listing, files=files)


def format_context_for_prompt(collected: CollectedContext) -> str:
    blocks: List[str] = []
    rel_root = collected.scope_root
    blocks.append("## Directory Listing")
    for line in collected.listing:
        blocks.append(f"- {line}")

    for path, text, truncated in collected.files:
        rel_path = path.relative_to(rel_root)
        blocks.append("")
        header = f"### File: {rel_path}"
        if truncated:
            header += " (truncated)"
        blocks.append(header)
        blocks.append("```")
        blocks.append(text)
        blocks.append("```")

    return "\n".join(blocks)


def format_context_for_display(collected: CollectedContext) -> str:
    blocks: List[str] = []
    rel_root = collected.scope_root
    blocks.append("## Directory Listing")
    for line in collected.listing:
        blocks.append(f"- {line}")

    for path, _text, _truncated in collected.files:
        rel_path = path.relative_to(rel_root)
        blocks.append("")
        label = "file" if path.is_file() else "entry"
        blocks.append(f"Reading {label}: {rel_path}")

    return "\n".join(blocks)
