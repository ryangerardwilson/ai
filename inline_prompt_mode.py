from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from inline_mode_renderer import InlineModeRenderer


@dataclass(frozen=True)
class InlinePromptRequest:
    prompt: str
    scopes: list[Path]


@dataclass(frozen=True)
class InlinePromptParseResult:
    request: Optional[InlinePromptRequest]
    error: Optional[str]


def parse_inline_prompt(argv: list[str]) -> Optional[InlinePromptParseResult]:
    if not argv:
        return None
    if any(arg.startswith("-") for arg in argv):
        return None

    scopes: list[Path] = []
    index = 0

    while index < len(argv):
        candidate = _resolve_arg_path(argv[index])
        if candidate is None or not candidate.exists():
            break
        scopes.append(candidate)
        index += 1

    if not scopes:
        prompt = " ".join(argv).strip()
        if not prompt:
            return InlinePromptParseResult(
                request=None, error="Inline prompt cannot be empty."
            )
        return InlinePromptParseResult(
            request=InlinePromptRequest(prompt=prompt, scopes=[]), error=None
        )

    prompt = " ".join(argv[index:]).strip()
    if not prompt:
        return InlinePromptParseResult(
            request=None,
            error="Inline prompt cannot be empty. Provide a question after the paths.",
        )
    return InlinePromptParseResult(
        request=InlinePromptRequest(prompt=prompt, scopes=scopes), error=None
    )


def run_inline_prompt(
    *,
    prompt: str,
    scopes: list[Path],
    renderer: object,
    config: dict,
    default_model: str,
) -> int:
    inline_renderer = InlineModeRenderer(
        renderer=renderer, config=config, default_model=default_model
    )
    return inline_renderer.run(prompt=prompt, scopes=scopes)


def _resolve_arg_path(arg: str) -> Optional[Path]:
    if not arg:
        return None
    candidate = Path(arg).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return candidate


__all__ = [
    "InlinePromptRequest",
    "InlinePromptParseResult",
    "parse_inline_prompt",
    "run_inline_prompt",
]
