#!/usr/bin/env python3
"""Collect repository context for the Codex-style analysis loop."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

DEFAULT_READ_LIMIT = 2000
MAX_LINE_LENGTH = 2000
MAX_READ_BYTES = 50 * 1024
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
class FileSlice:
    path: Path
    offset: int
    limit: int
    total_lines: int
    lines: List[str]  # line fragments without numbering
    truncated: bool
    truncated_by_bytes: bool
    preview: str

    @property
    def last_line_read(self) -> int:
        return self.offset + len(self.lines)

    @property
    def numbered_lines(self) -> List[str]:
        start = self.offset + 1
        return [f"{(start + idx):05d}| {line}" for idx, line in enumerate(self.lines)]


@dataclass
class CollectedContext:
    scope_root: Path
    listing: List[str]
    files: List[FileSlice]


def _is_binary(path: Path) -> bool:
    ext = path.suffix.lower()
    if ext in {
        ".zip",
        ".tar",
        ".gz",
        ".exe",
        ".dll",
        ".so",
        ".class",
        ".jar",
        ".war",
        ".7z",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".odt",
        ".ods",
        ".odp",
        ".bin",
        ".dat",
        ".obj",
        ".o",
        ".a",
        ".lib",
        ".wasm",
        ".pyc",
        ".pyo",
    }:
        return True

    try:
        with path.open("rb") as handle:
            chunk = handle.read(4096)
    except OSError:
        return False

    if not chunk:
        return False

    if b"\x00" in chunk:
        return True

    non_printable = sum(1 for byte in chunk if byte < 9 or (13 < byte < 32))
    return (non_printable / len(chunk)) > 0.3


def read_file_slice(
    path: Path,
    *,
    offset: int = 0,
    limit: int = DEFAULT_READ_LIMIT,
    max_bytes: int = MAX_READ_BYTES,
) -> FileSlice:
    if _is_binary(path):
        return FileSlice(
            path=path,
            offset=offset,
            limit=limit,
            total_lines=0,
            lines=["<binary file>"],
            truncated=False,
            truncated_by_bytes=False,
            preview="<binary file>",
        )

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        data = path.read_bytes()
        text = data.decode("utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover - filesystem issues
        return FileSlice(
            path=path,
            offset=offset,
            limit=limit,
            total_lines=0,
            lines=[f"<failed to read: {exc}>"],
            truncated=False,
            truncated_by_bytes=False,
            preview=f"<failed to read: {exc}>",
        )

    all_lines = text.split("\n")
    total_lines = len(all_lines)
    safe_offset = max(0, min(offset, total_lines))
    raw: List[str] = []
    bytes_used = 0
    truncated_by_bytes = False

    for line in all_lines[safe_offset : safe_offset + limit]:
        clipped = line if len(line) <= MAX_LINE_LENGTH else line[:MAX_LINE_LENGTH] + "..."
        size = len(clipped.encode("utf-8")) + (1 if raw else 0)
        if bytes_used + size > max_bytes:
            truncated_by_bytes = True
            break
        raw.append(clipped)
        bytes_used += size

    truncated = truncated_by_bytes or (safe_offset + len(raw) < total_lines)
    preview = "\n".join(raw[:20])

    return FileSlice(
        path=path,
        offset=safe_offset,
        limit=limit,
        total_lines=total_lines,
        lines=raw,
        truncated=truncated,
        truncated_by_bytes=truncated_by_bytes,
        preview=preview,
    )


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


def collect_context(
    scope: Path,
    *,
    limit_bytes: int = MAX_READ_BYTES,
    default_limit: int = DEFAULT_READ_LIMIT,
    include_listing: bool = False,
    file_windows: dict[Path, tuple[int, int]] | None = None,
) -> CollectedContext:
    scope_root = scope.resolve()
    listing: List[str] = []
    if include_listing:
        try:
            for entry in sorted(scope_root.iterdir()):
                mark = "/" if entry.is_dir() else ""
                listing.append(entry.name + mark)
        except FileNotFoundError:
            listing.append("<scope directory missing>")

    files: List[FileSlice] = []
    for candidate in _discover_candidates(scope_root):
        if len(files) >= MAX_FILES:
            break
        if candidate.is_dir():
            continue
        offset, limit = (0, default_limit)
        if file_windows and candidate in file_windows:
            offset, limit = file_windows[candidate]
        max_bytes = max(1, min(limit_bytes, MAX_READ_BYTES))
        window = read_file_slice(candidate, offset=offset, limit=max(1, limit), max_bytes=max_bytes)
        files.append(window)

    return CollectedContext(scope_root=scope_root, listing=listing, files=files)


def _slice_hint(file_slice: FileSlice) -> str:
    if file_slice.truncated_by_bytes:
        return (
            f"(Output truncated at {MAX_READ_BYTES} bytes. "
            f"Use 'offset' parameter to read beyond line {file_slice.last_line_read})"
        )
    if file_slice.truncated:
        return (
            f"(File has more lines. Use 'offset' parameter to read beyond line {file_slice.last_line_read})"
        )
    return f"(End of file - total {file_slice.total_lines} lines)"


def format_file_slice_for_prompt(file_slice: FileSlice, *, rel_root: Path | None = None) -> str:
    rel_path = file_slice.path
    if rel_root:
        try:
            rel_path = file_slice.path.relative_to(rel_root)
        except ValueError:
            rel_path = file_slice.path

    header = f"### File: {rel_path}"
    if file_slice.lines:
        header += f" (lines {file_slice.offset + 1}-{file_slice.last_line_read})"
    if file_slice.truncated:
        header += " (truncated)"

    numbered = file_slice.numbered_lines
    body = "\n".join(numbered) if numbered else "<empty file>"
    hint = _slice_hint(file_slice)
    parts = [
        header,
        "<file>",
        body,
        "",
        hint,
        "</file>",
    ]
    return "\n".join(parts)


def format_context_for_prompt(collected: CollectedContext) -> str:
    blocks: List[str] = []
    rel_root = collected.scope_root
    if collected.listing:
        blocks.append("## Directory Listing")
        for line in collected.listing:
            blocks.append(f"- {line}")

    for file_slice in collected.files:
        if blocks:
            blocks.append("")
        blocks.append(format_file_slice_for_prompt(file_slice, rel_root=rel_root))

    return "\n".join(blocks)


def format_context_for_display(collected: CollectedContext) -> str:
    blocks: List[str] = []
    rel_root = collected.scope_root
    if collected.listing:
        blocks.append("## Directory Listing")
        for line in collected.listing:
            blocks.append(f"- {line}")

    for file_slice in collected.files:
        rel_path = file_slice.path.relative_to(rel_root)
        if blocks:
            blocks.append("")
        label = "file" if file_slice.path.is_file() else "entry"
        descriptor = (
            f"offset={file_slice.offset} limit={file_slice.limit} "
            f"lines_read={len(file_slice.lines)} truncated={file_slice.truncated}"
        )
        blocks.append(f"Reading {label}: {rel_path} ({descriptor})")

    return "\n".join(blocks)
