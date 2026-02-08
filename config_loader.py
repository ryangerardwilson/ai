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

DEFAULT_MODEL = "gpt-5-codex"

DEFAULTS: Dict[str, Any] = {
    "openai_api_key": "",
    "model": DEFAULT_MODEL,
    "dog_whistle": "",
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

    cfg.pop("context_settings", None)

    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key:
        cfg["openai_api_key"] = env_key

    env_model = os.environ.get("AI_MODEL")
    if env_model:
        cfg["model"] = env_model

    env_dog = os.environ.get("DOG_WHISTLE")
    if env_dog:
        cfg["dog_whistle"] = env_dog

    return cfg


def ensure_config_dir_exists() -> Path:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def save_config(config: Dict[str, Any]) -> Path:
    path = ensure_config_dir_exists()
    payload: Dict[str, Any] = {
        "openai_api_key": config.get("openai_api_key", ""),
        "model": config.get("model", DEFAULT_MODEL),
        "dog_whistle": config.get("dog_whistle", "jfdi"),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


__all__ = [
    "load_config",
    "ensure_config_dir_exists",
    "save_config",
    "DEFAULTS",
    "DEFAULT_MODEL",
]
