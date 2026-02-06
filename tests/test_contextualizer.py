from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextualizer import (
    read_file_slice,
    format_file_slice_for_prompt,
    collect_context,
    DEFAULT_READ_LIMIT,
    MAX_READ_BYTES,
    CollectedContext,
)


def _write_temp_file(lines: int) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", delete=False)
    with tmp as handle:
        for idx in range(lines):
            handle.write(f"line-{idx}\n")
    return Path(tmp.name)


def test_read_file_slice_truncates_when_limit_hits():
    path = _write_temp_file(10)
    try:
        slice_info = read_file_slice(path, limit=5, max_bytes=MAX_READ_BYTES)
        assert slice_info.offset == 0
        assert slice_info.last_line_read == 5
        assert slice_info.truncated is True
        assert slice_info.numbered_lines[0].endswith("line-0")
        snippet = format_file_slice_for_prompt(slice_info, rel_root=path.parent)
        assert "Use 'offset' parameter" in snippet
    finally:
        path.unlink(missing_ok=True)


def test_read_file_slice_uses_offset():
    path = _write_temp_file(DEFAULT_READ_LIMIT + 5)
    try:
        slice_info = read_file_slice(
            path, offset=DEFAULT_READ_LIMIT, limit=5, max_bytes=MAX_READ_BYTES
        )
        assert slice_info.offset == DEFAULT_READ_LIMIT
        assert slice_info.last_line_read == DEFAULT_READ_LIMIT + 5
        assert slice_info.truncated is True
    finally:
        path.unlink(missing_ok=True)


def test_collect_context_skips_listing_by_default(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello\nworld\n")
    context = collect_context(tmp_path)
    assert isinstance(context, CollectedContext)
    assert context.listing == []
