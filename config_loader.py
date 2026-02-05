#!/usr/bin/env python3
"""Config loader for ai.

Loads JSON config from the XDG path, applies defaults, and honors
environment overrides for compatibility with existing workflows.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from config_paths import get_config_path
from contextualizer import DEFAULT_READ_LIMIT, MAX_READ_BYTES

DEFAULT_SYSTEM_PROMPT = (
    "Channel a blunt, no-nonsense, technically brutal critique style"
)

DEFAULT_MODELS: Dict[str, str] = {
    "chat": "gpt-5.2",
    "prompt": "gpt-5-mini",
    "edit": "gpt-5-codex",
    "bash": "gpt-5-codex",
}

DEFAULT_BASH_SETTINGS: Dict[str, Any] = {
    "max_seconds": 15,
    "max_output_bytes": 20000,
    "max_iterations": 6,
}

DEFAULT_CONTEXT_SETTINGS: Dict[str, Any] = {
    "read_limit": DEFAULT_READ_LIMIT,
    "max_bytes": MAX_READ_BYTES,
    "include_listing": False,
}

DEFAULTS: Dict[str, Any] = {
    "openai_api_key": "",
    "models": DEFAULT_MODELS.copy(),
    "system_instruction": DEFAULT_SYSTEM_PROMPT,
    "bash_settings": DEFAULT_BASH_SETTINGS.copy(),
    "context_settings": DEFAULT_CONTEXT_SETTINGS.copy(),
}


def load_config() -> Dict[str, Any]:
    path = get_config_path()
    data: Dict[str, Any] = {}

    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - fall back to defaults if unreadable
            data = {}

    cfg = {**DEFAULTS, **data}

    models_entry = data.get("models")
    models_from_file = models_entry if isinstance(models_entry, dict) else {}
    cfg["models"] = {**dict(DEFAULT_MODELS), **models_from_file}

    bash_entry = data.get("bash_settings")
    bash_settings_from_file = bash_entry if isinstance(bash_entry, dict) else {}
    cfg["bash_settings"] = {**dict(DEFAULT_BASH_SETTINGS), **bash_settings_from_file}

    context_entry = data.get("context_settings")
    context_settings_from_file = (
        context_entry if isinstance(context_entry, dict) else {}
    )
    cfg["context_settings"] = {
        **dict(DEFAULT_CONTEXT_SETTINGS),
        **context_settings_from_file,
    }

    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key:
        cfg["openai_api_key"] = env_key

    env_model = os.environ.get("AI_MODEL")
    if env_model:
        cfg["models"] = {mode: env_model for mode in DEFAULT_MODELS.keys()}

    for mode in DEFAULT_MODELS.keys():
        env_specific = os.environ.get(f"AI_MODEL_{mode.upper()}")
        if env_specific:
            cfg["models"][mode] = env_specific

    env_system = os.environ.get("AI_SYSTEM_PROMPT")
    if env_system:
        cfg["system_instruction"] = env_system

    env_bash_seconds = os.environ.get("AI_BASH_MAX_SECONDS")
    if env_bash_seconds and env_bash_seconds.isdigit():
        cfg["bash_settings"]["max_seconds"] = int(env_bash_seconds)

    env_bash_output = os.environ.get("AI_BASH_MAX_OUTPUT")
    if env_bash_output and env_bash_output.isdigit():
        cfg["bash_settings"]["max_output_bytes"] = int(env_bash_output)

    env_bash_iters = os.environ.get("AI_BASH_MAX_ITERATIONS")
    if env_bash_iters and env_bash_iters.isdigit():
        cfg["bash_settings"]["max_iterations"] = int(env_bash_iters)

    env_context_limit = os.environ.get("AI_CONTEXT_READ_LIMIT")
    if env_context_limit and env_context_limit.isdigit():
        cfg["context_settings"]["read_limit"] = int(env_context_limit)

    env_context_bytes = os.environ.get("AI_CONTEXT_MAX_BYTES")
    if env_context_bytes and env_context_bytes.isdigit():
        cfg["context_settings"]["max_bytes"] = int(env_context_bytes)

    env_context_listing = os.environ.get("AI_CONTEXT_INCLUDE_LISTING")
    if env_context_listing:
        cfg["context_settings"]["include_listing"] = env_context_listing.lower() in {
            "1",
            "true",
            "yes",
        }

    return cfg


def ensure_config_dir_exists() -> Path:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


__all__ = [
    "load_config",
    "ensure_config_dir_exists",
    "DEFAULTS",
    "DEFAULT_MODELS",
    "DEFAULT_SYSTEM_PROMPT",
    "DEFAULT_BASH_SETTINGS",
    "DEFAULT_CONTEXT_SETTINGS",
]
