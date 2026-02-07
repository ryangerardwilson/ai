from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class EngineSettings:
    api_key: str
    default_model: str
    show_reasoning: bool
    reasoning_effort: str
    debug_api: bool


def resolve_api_key(
    candidate: str | None = None, config: Optional[Dict[str, Any]] = None
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
    raise RuntimeError("OpenAI API key not configured")


def resolve_model(
    mode: str,
    config: Optional[Dict[str, Any]] = None,
    override: Optional[str] = None,
    default_model: str = "gpt-5-codex",
) -> str:
    if override:
        return override
    cfg = config or {}
    candidate = cfg.get("model")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return default_model


def _compute_show_reasoning(config: Dict[str, Any]) -> bool:
    env_toggle = os.environ.get("AI_SHOW_REASONING")
    if env_toggle is None:
        env_toggle = os.environ.get("AI_SHOW_THINKING")
    config_value = config.get("show_reasoning")
    if config_value is None:
        config_value = config.get("show_thinking", True)
    if env_toggle is not None:
        return env_toggle.lower() not in {"0", "false", "no"}
    return bool(config_value)


def _compute_reasoning_effort(config: Dict[str, Any]) -> str:
    env_effort = os.environ.get("AI_REASONING_EFFORT")
    config_effort = config.get("reasoning_effort")
    if env_effort:
        return env_effort
    if isinstance(config_effort, str) and config_effort:
        return config_effort
    return "medium"


def _compute_debug_flag() -> bool:
    debug_env = os.environ.get("AI_DEBUG_REASONING") or os.environ.get("AI_DEBUG_API")
    return bool(debug_env)


def build_engine_settings(
    config: Dict[str, Any], default_model: str = "gpt-5-codex"
) -> EngineSettings:
    return EngineSettings(
        api_key=resolve_api_key(config=config),
        default_model=default_model,
        show_reasoning=_compute_show_reasoning(config),
        reasoning_effort=_compute_reasoning_effort(config),
        debug_api=_compute_debug_flag(),
    )


__all__ = [
    "EngineSettings",
    "build_engine_settings",
    "resolve_api_key",
    "resolve_model",
]
