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

DEFAULT_SYSTEM_PROMPT = (
    "Channel a blunt, no-nonsense, technically brutal critique style"
)

DEFAULT_MODELS: Dict[str, str] = {
    "chat": "gpt-5.2",
    "prompt": "gpt-5-mini",
    "edit": "gpt-5-codex",
}

DEFAULTS: Dict[str, Any] = {
    "openai_api_key": "",
    "models": DEFAULT_MODELS.copy(),
    "system_instruction": DEFAULT_SYSTEM_PROMPT,
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

    models_from_file = data.get("models") if isinstance(data.get("models"), dict) else {}
    cfg["models"] = {**DEFAULT_MODELS, **models_from_file}

    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key:
        cfg["openai_api_key"] = env_key

    env_model = os.environ.get("AI_MODEL")
    if env_model:
        cfg["models"] = {mode: env_model for mode in DEFAULT_MODELS}

    for mode in DEFAULT_MODELS:
        env_specific = os.environ.get(f"AI_MODEL_{mode.upper()}")
        if env_specific:
            cfg["models"][mode] = env_specific

    env_system = os.environ.get("AI_SYSTEM_PROMPT")
    if env_system:
        cfg["system_instruction"] = env_system

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
]
