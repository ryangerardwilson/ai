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

DEFAULT_MODEL = "gpt-5-codex"

DEFAULT_CONTEXT_SETTINGS: Dict[str, Any] = {
    "read_limit": DEFAULT_READ_LIMIT,
    "max_bytes": MAX_READ_BYTES,
    "include_listing": False,
}

DEFAULTS: Dict[str, Any] = {
    "openai_api_key": "",
    "model": DEFAULT_MODEL,
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
        cfg["model"] = env_model

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
    "DEFAULT_MODEL",
    "DEFAULT_BASH_SETTINGS",
    "DEFAULT_CONTEXT_SETTINGS",
]
